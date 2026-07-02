"""Pure, I/O-free interactive play controller for one craps game.

Where ``run_session`` drives a strategy through a whole session in one call, this
module models an INTERACTIVE game: a human (or a future API/UI layer) places
bets between individual rolls. The :class:`PlayController` owns a
:class:`~craps_engine.session.Table` plus a :class:`~craps_engine.dice.Dice`
source and a :class:`~craps_engine.session.SessionConfig`, and it interleaves
human bet-placement with :meth:`PlayController.roll`.

Purity contract: NO printing, NO file access, NO web/UI imports. Every method
returns a structured, serializable value; rendering those values is the caller's
job. Reusing ``SessionConfig`` (rather than inventing a new config) and the
central ``serialize_fraction`` serializer keeps this layer DRY with the session
runner.

The single ``place_bet`` funnel is deliberate: the free-text entry
(:meth:`PlayController.place_bet_text`) and the common-bet BUTTONS a UI exposes
(``pass``, ``dontpass``, ``place 6``, ``place 8``, ``take <point>``) both build a
:class:`~craps_engine.specs.BetSpec` and flow through the ONE
:meth:`PlayController.place_bet` path, so legality and id-assignment live in
exactly one place.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from fractions import Fraction
from typing import TYPE_CHECKING, TypedDict

from craps_engine.bets.base import ResolutionStatus
from craps_engine.bets.odds import MAX_ODDS_MULTIPLIER, _OddsBet
from craps_engine.bets.place import PlaceBet
from craps_engine.money import serialize_fraction
from craps_engine.registry import snap_to_place_unit
from craps_engine.session import SessionConfig, Table
from craps_engine.specs import BetSpec, build_bet, parse_bet_spec
from craps_engine.state import GameState, Phase

if TYPE_CHECKING:
    from collections.abc import Callable

    from craps_engine.bets.base import Bet, BetPayload, Resolution, ResolutionPayload
    from craps_engine.dice import Dice, DiceRoll, DiceRollPayload
    from craps_engine.money import FractionPayload

# The odds kinds that are legal only once a point is established.
_ODDS_KINDS = frozenset({"take", "lay"})

# The Don't-side bet kinds, refused entirely under a ruleset that does not offer
# the Don't side (e.g. crapless craps).
_DONT_KINDS = frozenset({"dontpass", "dontcome", "lay"})

#: Odds kind -> (flat backer class, come backer class, this side's odds class,
#: backer label for messages). Take odds are backed by a Pass Line flat on the
#: PUCK point OR a Come bet riding this come-point; lay odds by a Don't Pass flat
#: on the puck point OR a Don't Come riding this come-point. Because a come-point
#: can never equal the puck point (making the point ends the point phase), a
#: given odds ``number`` unambiguously identifies which it backs. Name-string
#: matching mirrors the ``_LINE_BET_NAMES`` idiom.
_ODDS_BACKING: dict[str, tuple[str, str, str, str]] = {
    "take": ("PassLine", "ComeBet", "TakeOdds", "Pass Line/Come"),
    "lay": ("DontPass", "DontCome", "LayOdds", "Don't Pass/Don't Come"),
}

#: Max rolls retained/shown in the recent-roll history tracker.
_RECENT_ROLLS_CAP = 10


def _dollar_str(value: Fraction) -> str:
    """Format an exact money :class:`Fraction` as a bare dollar amount.

    Whole amounts render as an int (``50``); a fractional amount falls back to a
    float (``12.5``). Used only for the human-readable odds-rejection messages.
    """
    return str(value.numerator) if value.denominator == 1 else str(float(value))


class GameViewPayload(TypedDict):
    """Serialized shape of a :class:`GameView`.

    Every monetary field is a non-percent :class:`~craps_engine.money.FractionPayload`;
    ``active_bets`` / ``last_outcomes`` are lists of the bets' / resolutions' own
    payloads; ``last_roll`` is a :class:`~craps_engine.dice.DiceRollPayload` or
    ``None``; the remaining fields are JSON-friendly primitives, so any UI / API
    layer consumes one fixed shape.
    """

    starting_bankroll: FractionPayload
    bankroll: FractionPayload
    running_net: FractionPayload
    phase: str
    point: int | None
    active_bets: list[BetPayload]
    last_roll: DiceRollPayload | None
    last_outcomes: list[ResolutionPayload]
    recent_rolls: list[DiceRollPayload]
    rolls_used: int
    rolls_left: int | None
    game_over: bool
    game_over_reason: str | None
    odds_available: bool
    variant: str
    point_numbers: list[int]
    allow_dont: bool


class PlaceOutcomePayload(TypedDict):
    """Serialized shape of a :class:`PlaceOutcome` (``{ok, message, view}``)."""

    ok: bool
    message: str
    view: GameViewPayload


class RollOutcomePayload(TypedDict):
    """Serialized shape of a :class:`RollOutcome` (``{ok, message, view}``)."""

    ok: bool
    message: str
    view: GameViewPayload


@dataclass(frozen=True)
class GameView:
    """An immutable, serializable snapshot of the whole game for the UI/API.

    Everything a caller needs to render one moment of play: the money position
    (starting/current/net), the table phase and point, the live bets, the most
    recent roll and its resolutions, roll accounting, and the game-over flags.
    Frozen so a view is a safe value to pass around and log.
    """

    #: Bankroll the shooter started with.
    starting_bankroll: Fraction
    #: Current wallet/cash bankroll (net worth minus stakes on the felt); see
    #: :meth:`PlayController.snapshot`.
    bankroll: Fraction
    #: Net change since the start (``bankroll - starting_bankroll``).
    running_net: Fraction
    #: The table phase as a stable string (:attr:`~craps_engine.state.Phase.value`).
    phase: str
    #: The live point number, or ``None`` on the come-out.
    point: int | None
    #: The bets live on the table after the last roll's pruning.
    active_bets: list[Bet]
    #: The most recent roll, or ``None`` before the first roll.
    last_roll: DiceRoll | None
    #: The resolutions produced by the most recent roll (empty before the first).
    last_outcomes: list[Resolution]
    #: The most recent rolls, newest-first, capped at 10 (empty before the first).
    recent_rolls: list[DiceRoll]
    #: Number of rolls executed so far.
    rolls_used: int
    #: Rolls remaining before the max-rolls cap (``max_rolls - rolls_used``), or
    #: ``None`` when uncapped (``config.max_rolls is None``).
    rolls_left: int | None
    #: Whether the game has ended.
    game_over: bool
    #: Why the game ended, or ``None`` while it is live.
    game_over_reason: str | None
    #: True iff odds may be placed now (i.e. the phase is POINT).
    odds_available: bool
    #: The rules variant name (e.g. ``"standard"``, ``"crapless"``).
    variant: str
    #: The point/box numbers offered by the variant (sorted).
    point_numbers: list[int]
    #: Whether the Don't side is offered under the variant.
    allow_dont: bool

    def to_dict(self) -> GameViewPayload:
        """Serialize to a JSON-friendly dict.

        Money fields go through the central ``serialize_fraction`` (as plain
        amounts, not percentages); bets and resolutions delegate to their own
        ``to_dict``; the last roll serializes to a dict or ``None``. Plain
        ints/bools/str/None pass through unchanged.
        """
        return {
            "starting_bankroll": serialize_fraction(self.starting_bankroll, as_percent=False),
            "bankroll": serialize_fraction(self.bankroll, as_percent=False),
            "running_net": serialize_fraction(self.running_net, as_percent=False),
            "phase": self.phase,
            "point": self.point,
            "active_bets": [bet.to_dict() for bet in self.active_bets],
            "last_roll": self.last_roll.to_dict() if self.last_roll else None,
            "last_outcomes": [res.to_dict() for res in self.last_outcomes],
            "recent_rolls": [r.to_dict() for r in self.recent_rolls],
            "rolls_used": self.rolls_used,
            "rolls_left": self.rolls_left,
            "game_over": self.game_over,
            "game_over_reason": self.game_over_reason,
            "odds_available": self.odds_available,
            "variant": self.variant,
            "point_numbers": self.point_numbers,
            "allow_dont": self.allow_dont,
        }


@dataclass(frozen=True)
class PlaceOutcome:
    """The result of one bet-placement attempt.

    ``ok`` reports acceptance; ``message`` is a human-readable note (why it was
    rejected, or a confirmation); ``view`` is the post-attempt snapshot so the
    caller always has a fresh render even on rejection.
    """

    ok: bool
    message: str
    view: GameView

    def to_dict(self) -> PlaceOutcomePayload:
        """Serialize to ``{ok, message, view}`` with the view expanded."""
        return {"ok": self.ok, "message": self.message, "view": self.view.to_dict()}


@dataclass(frozen=True)
class RollOutcome:
    """The result of one :meth:`PlayController.roll`.

    Same shape as :class:`PlaceOutcome`: ``ok`` is False only when the roll was
    refused (the game is already over); ``view`` is the post-roll snapshot.
    """

    ok: bool
    message: str
    view: GameView

    def to_dict(self) -> RollOutcomePayload:
        """Serialize to ``{ok, message, view}`` with the view expanded."""
        return {"ok": self.ok, "message": self.message, "view": self.view.to_dict()}


class PlayController:
    """A pure interactive craps game: place bets between rolls, read snapshots.

    Owns a :class:`~craps_engine.session.Table` (seeded from the config's
    starting bankroll), a :class:`~craps_engine.dice.Dice` source, and the
    :class:`~craps_engine.session.SessionConfig`. A monotonic counter assigns
    every placed bet a unique id. All mutation happens through
    :meth:`place_bet` / :meth:`roll`; :meth:`snapshot` is a pure read.
    """

    def __init__(self, dice: Dice, config: SessionConfig) -> None:
        """Create a controller on a fresh table for ``config``'s bankroll."""
        self._dice = dice
        self._config = config
        #: The rules variant in force for this game (drives placement legality +
        #: the come-out settlement of every bet via the shared GameState).
        self._ruleset = config.ruleset
        self._table = Table(config.starting_bankroll, GameState(config.ruleset))
        #: Monotonic id source so every placed bet gets a distinct id.
        self._counter = 0
        self._rolls_used = 0
        self._last_roll: DiceRoll | None = None
        self._last_outcomes: list[Resolution] = []
        #: Bet ids already pressed since the last roll; reset each roll so a
        #: given bet's win can be pressed at most once (see :meth:`press_bet`).
        self._pressed_this_roll: set[str] = set()
        self._history: deque[DiceRoll] = deque(maxlen=_RECENT_ROLLS_CAP)
        self._game_over = False
        self._reason: str | None = None

    def snapshot(self) -> GameView:
        """Build a :class:`GameView` from the current table/config/roll state.

        The view reports a **wallet/cash** bankroll, not the engine's net-worth
        bankroll: it is the free cash a player could pick up right now, i.e. the
        net-worth bankroll minus every stake sitting on the felt. The identity is

            wallet = net_worth - sum(active bet stakes)
            => wallet + at_risk == net_worth   (always)

        so placing a bet lowers the shown bankroll (cash moves onto the felt),
        removing one raises it (chips come back as cash), and a win raises it by
        the profit. ``running_net`` is measured off this wallet, so both the
        bankroll AND the net move on every place/remove -- the intuitive
        cash-in-hand model an interactive player expects. The underlying
        net-worth engine (:meth:`Table.settle`, the analyzer, Monte Carlo) is
        untouched; this is purely how the interactive view is presented.

        Game-over is deliberately NOT computed from this wallet figure (see
        :meth:`_check_game_over`): chips resting on the felt are still yours, so
        you are only bust when your NET WORTH is gone, not merely when your cash
        is temporarily committed to bets.
        """
        on_table = sum(
            (bet.amount for bet in self._table.active_bets()),
            start=Fraction(0),
        )
        starting = self._config.starting_bankroll
        wallet = self._table.bankroll - on_table
        phase = self._table.state.phase
        ruleset = self._table.state.ruleset
        max_rolls = self._config.max_rolls
        rolls_left = None if max_rolls is None else max_rolls - self._rolls_used
        return GameView(
            starting_bankroll=starting,
            bankroll=wallet,
            running_net=wallet - starting,
            phase=phase.value,
            point=self._table.state.point,
            active_bets=self._table.active_bets(),
            last_roll=self._last_roll,
            last_outcomes=list(self._last_outcomes),
            recent_rolls=list(reversed(self._history)),
            rolls_used=self._rolls_used,
            rolls_left=rolls_left,
            game_over=self._game_over,
            game_over_reason=self._reason,
            odds_available=phase is Phase.POINT,
            variant=ruleset.name,
            point_numbers=sorted(ruleset.point_numbers),
            allow_dont=ruleset.allow_dont,
        )

    def place_bet(self, spec: BetSpec) -> PlaceOutcome:
        """Place one validated :class:`BetSpec`; NEVER raises.

        Illegal placements are rejected with ``ok=False`` and a message rather
        than an exception: the game being over, or odds that back neither the
        current puck point nor an established come-point (or that break the
        flat-bet / 3-4-5x table rules). On success the bet is added to the table
        with a freshly-minted unique id.
        """
        if self._game_over:
            return PlaceOutcome(
                ok=False,
                message=f"game over ({self._reason})",
                view=self.snapshot(),
            )

        ruleset_rejection = self._reject_against_ruleset(spec)
        if ruleset_rejection is not None:
            return ruleset_rejection

        if spec.kind in _ODDS_KINDS:
            rejection = self._reject_illegal_odds(spec)
            if rejection is not None:
                return rejection

        bet_id = f"{spec.kind}{self._counter}"
        self._counter += 1
        bet = build_bet(spec, bet_id)
        self._table.add_bet(bet)
        return PlaceOutcome(
            ok=True,
            message=f"placed {spec.kind} {bet_id}",
            view=self.snapshot(),
        )

    def _reject_against_ruleset(self, spec: BetSpec) -> PlaceOutcome | None:
        """Reject a bet the active ruleset does not permit; else ``None``.

        Two gates, both returning an ``ok=False`` outcome (never raising):

        * **Don't-side gate.** A variant with ``allow_dont=False`` (crapless
          craps) offers no Don't Pass / Don't Come / Lay, so those are refused.
        * **Number gate.** A numbered bet (place/take/lay) on a total that is not
          a point number under this ruleset is refused -- e.g. ``place 2`` under
          standard craps, or a stray ``take 7``.
        """
        ruleset = self._ruleset
        if not ruleset.allow_dont and spec.kind in _DONT_KINDS:
            return PlaceOutcome(
                ok=False,
                message=f"Don't bets aren't offered in {ruleset.name} craps",
                view=self.snapshot(),
            )
        if spec.number is not None and spec.number not in ruleset.point_numbers:
            return PlaceOutcome(
                ok=False,
                message=f"{spec.number} isn't a point number in {ruleset.name} craps",
                view=self.snapshot(),
            )
        return None

    def _reject_illegal_odds(self, spec: BetSpec) -> PlaceOutcome | None:
        """Return a rejection for illegal take/lay odds, else ``None``.

        Odds are legal only when they back an active number -- either the CURRENT
        puck point or an established come-point on the matching side (a Come bet
        for take odds, a Don't Come for lay) -- and only as true "behind the line"
        wagers: they need a flat/come bet behind them and may not exceed the
        3-4-5x table maximum (delegated to :meth:`_reject_odds_table_rules`).
        Because a come-point never equals the puck point, the odds ``number``
        alone identifies which it backs, so this also covers come-odds placed
        while the table sits on the come-out. Returns ``None`` when legal.
        """
        number = spec.number
        if number is None:  # pragma: no cover - the parser guarantees odds carry a number
            return PlaceOutcome(
                ok=False,
                message="odds must name a point",
                view=self.snapshot(),
            )
        puck = self._table.state.point
        backs_puck = puck is not None and number == puck
        _flat, come_name, _odds, _label = _ODDS_BACKING[spec.kind]
        backs_come_point = any(
            type(bet).__name__ == come_name and getattr(bet, "come_point", None) == number
            for bet in self._table.active_bets()
        )
        if not backs_puck and not backs_come_point:
            return PlaceOutcome(
                ok=False,
                message="odds must back the current point or an established come-point",
                view=self.snapshot(),
            )
        return self._reject_odds_table_rules(spec, number)

    def _reject_odds_table_rules(self, spec: BetSpec, number: int) -> PlaceOutcome | None:
        """Reject naked or over-max odds; return ``None`` when the odds are legal.

        Enforces two real-casino table rules at PLACEMENT time (an odds bet's
        ``resolve`` still settles whatever stake is down -- see the MAX-ODDS
        POLICY note in :mod:`craps_engine.bets.odds`):

        * **A backing bet is required.** Take odds must be backed by a Pass Line
          bet on the puck point OR a Come bet riding this ``number``; lay odds by a
          Don't Pass on the puck point OR a Don't Come riding ``number``. Without
          one the odds are "naked" and refused.
        * **3-4-5x maximum.** The total odds on ``number`` may not exceed the
          pooled backing times its cap (3x on 4/10, 4x on 5/9, 5x on 6/8, from
          :data:`~craps_engine.bets.odds.MAX_ODDS_MULTIPLIER`). Odds already on the
          number pool toward that ceiling, so repeated placements/presses can't
          slip past it.
        """
        flat_name, come_name, odds_name, flat_label = _ODDS_BACKING[spec.kind]
        puck = self._table.state.point
        backs_puck = puck is not None and number == puck
        backing = sum(
            (
                bet.amount
                for bet in self._table.active_bets()
                if (backs_puck and type(bet).__name__ == flat_name)
                or (type(bet).__name__ == come_name and getattr(bet, "come_point", None) == number)
            ),
            Fraction(0),
        )
        if backing == 0:
            return PlaceOutcome(
                ok=False,
                message=f"{spec.kind} odds require a {flat_label} bet on {number}",
                view=self.snapshot(),
            )
        existing = sum(
            (
                bet.amount
                for bet in self._table.active_bets()
                if type(bet).__name__ == odds_name and getattr(bet, "number", None) == number
            ),
            Fraction(0),
        )
        mult = MAX_ODDS_MULTIPLIER[number]
        max_odds = mult * backing
        if existing + spec.amount > max_odds:
            return PlaceOutcome(
                ok=False,
                message=(
                    f"odds exceed the {mult}x max on {number} "
                    f"(max ${_dollar_str(max_odds)}, ${_dollar_str(existing)} already up)"
                ),
                view=self.snapshot(),
            )
        return None

    def place_bet_text(self, text: str) -> PlaceOutcome:
        """Parse free text into a :class:`BetSpec` and place it; NEVER raises.

        A parse failure is reported as a rejection (``ok=False``) carrying the
        parser's message; a successful parse flows through the same
        :meth:`place_bet` funnel the buttons use.
        """
        try:
            spec = parse_bet_spec(text)
        except ValueError as exc:
            return PlaceOutcome(ok=False, message=str(exc), view=self.snapshot())
        return self.place_bet(spec)

    def remove_bet(self, bet_id: str) -> PlaceOutcome:
        """Take a mis-clicked bet off the table by id; NEVER raises.

        Practice-friendly with no contract-bet locking: any live bet may come
        down. Refused (``ok=False``) once the game is over -- matching
        :meth:`place_bet` -- and rejected when no live bet carries ``bet_id``.
        On success the bet is removed and a fresh snapshot returned.

        Under the wallet/cash view (:meth:`snapshot`) removing a bet RAISES the
        shown bankroll and net: the stake was displayed as committed to the felt,
        so taking it off returns that cash to the wallet. (The engine's net-worth
        bankroll is unchanged -- a standing stake was always counted as net
        worth -- but the wallet the view reports goes up because there is one
        fewer stake to subtract.) Reuses the :class:`PlaceOutcome` shape so
        callers handle placement and removal results identically.
        """
        if self._game_over:
            return PlaceOutcome(
                ok=False,
                message=f"game over ({self._reason})",
                view=self.snapshot(),
            )

        removed = self._table.remove_bet(bet_id)
        if removed is None:
            return PlaceOutcome(
                ok=False,
                message=f"no bet with id {bet_id!r} to remove",
                view=self.snapshot(),
            )
        return PlaceOutcome(
            ok=True,
            message=f"removed {bet_id}",
            view=self.snapshot(),
        )

    def press_bet(self, bet_id: str, *, snap_place_to_unit: bool = False) -> PlaceOutcome:
        """Press a bet BY ITS WINNINGS from the most recent roll; NEVER raises.

        "Pressing" grows a wager using the money it just won: the bet's
        ``amount`` is increased by the ``delta`` of that bet's WIN in the LAST
        roll's outcomes. It is therefore valid ONLY immediately after that bet's
        winning roll -- there must be a fresh :class:`~craps_engine.bets.base.Resolution`
        with matching ``bet_id`` and ``WIN`` status in :attr:`_last_outcomes`.

        A given bet's win may be pressed AT MOST ONCE per roll: the press
        CONSUMES that win, so a second press before the next roll is refused
        (repeatedly clicking a UI Press button cannot compound the stake off a
        single win). The next roll's win re-enables pressing that bet.

        Refused (``ok=False``) once the game is over, when no live bet carries
        ``bet_id``, when that bet did not win on the last roll (nothing to
        press), or when that win was already pressed this roll. On success the
        amount grows and a fresh snapshot is returned.

        Pressing is net-worth-neutral -- the winnings were already credited at
        settle time, and pressing just moves that cash onto the felt as chips.
        Under the wallet/cash view (:meth:`snapshot`) that cash->chips transfer
        LOWERS the shown bankroll (the pressed amount is now at risk) while net
        worth stays put; ``at_risk`` rises by the same amount. Reuses the
        :class:`PlaceOutcome` shape so callers handle it like a placement result.

        When ``snap_place_to_unit`` is set and the pressed bet is a Place bet, the
        grown stake is rounded to the nearest whole multiple of that number's
        optimal unit (:func:`~craps_engine.registry.snap_to_place_unit`) so the
        pressed wager keeps paying whole dollars -- the play-mode felt opts in so
        pressing mirrors the same unit snapping placement uses. Left off by
        default, so the exact "grow by winnings" behaviour is unchanged for the
        JSON API and other callers.
        """
        if self._game_over:
            return PlaceOutcome(
                ok=False,
                message=f"game over ({self._reason})",
                view=self.snapshot(),
            )

        bet = next((b for b in self._table.active_bets() if b.id == bet_id), None)
        if bet is None:
            return PlaceOutcome(
                ok=False,
                message=f"no bet with id {bet_id!r} to press",
                view=self.snapshot(),
            )

        win = next(
            (
                res
                for res in self._last_outcomes
                if res.bet_id == bet_id and res.status is ResolutionStatus.WIN
            ),
            None,
        )
        if win is None:
            return PlaceOutcome(
                ok=False,
                message=f"bet {bet_id!r} did not win on the last roll; nothing to press",
                view=self.snapshot(),
            )
        if bet_id in self._pressed_this_roll:
            return PlaceOutcome(
                ok=False,
                message=f"bet {bet_id!r} already pressed this roll",
                view=self.snapshot(),
            )

        grown = bet.amount + win.delta
        if snap_place_to_unit and isinstance(bet, PlaceBet):
            # Round the grown stake to whole dollars, then to its unit multiple.
            grown = Fraction(snap_to_place_unit(bet.number, round(grown)))
        bet.amount = grown
        self._pressed_this_roll.add(bet_id)
        return PlaceOutcome(
            ok=True,
            message=f"pressed {bet_id} to {bet.amount}",
            view=self.snapshot(),
        )

    def set_come_out_working(self, bet_id: str, *, working: bool) -> PlaceOutcome:
        """Call an odds bet ON or OFF for the come-out roll; NEVER raises.

        Free odds ride OFF on the come-out by default (real-table behaviour); this
        lets a player working a come-bet's odds "call them on" so they settle on
        the come-out too (or turn them back off). Only odds bets carry the
        ``come_out_working`` flag, so this is refused for any other bet type.

        Refused (``ok=False``) once the game is over, when no live bet carries
        ``bet_id``, or when that bet is not an odds bet. On success the flag is set
        and a fresh snapshot returned, reusing the :class:`PlaceOutcome` shape so
        callers handle it like a placement result.
        """
        if self._game_over:
            return PlaceOutcome(
                ok=False,
                message=f"game over ({self._reason})",
                view=self.snapshot(),
            )

        bet = next((b for b in self._table.active_bets() if b.id == bet_id), None)
        if bet is None:
            return PlaceOutcome(
                ok=False,
                message=f"no bet with id {bet_id!r} to toggle",
                view=self.snapshot(),
            )
        if not isinstance(bet, _OddsBet):
            return PlaceOutcome(
                ok=False,
                message=f"bet {bet_id!r} is not an odds bet; only odds work on the come-out",
                view=self.snapshot(),
            )

        bet.come_out_working = working
        state = "on" if working else "off"
        return PlaceOutcome(
            ok=True,
            message=f"called {bet_id} odds {state} for the come-out",
            view=self.snapshot(),
        )

    def roll(self) -> RollOutcome:
        """Roll the dice, settle the table, and check the game-over gates.

        Refuses (``ok=False``) once the game is over. Otherwise it rolls, settles
        every live bet via :meth:`Table.settle`, records the roll/outcomes, and
        evaluates the termination gates with precedence BUST -> GOAL ->
        MAX-ROLLS.
        """
        if self._game_over:
            return RollOutcome(
                ok=False,
                message=f"game over ({self._reason})",
                view=self.snapshot(),
            )

        roll = self._dice.roll()
        settle = self._table.settle(roll)
        self._last_roll = roll
        self._last_outcomes = [res for _bet, res in settle.settled]
        # A new roll re-enables pressing each bet's fresh win (empty set each roll).
        self._pressed_this_roll = set()
        self._history.append(roll)
        self._rolls_used += 1

        self._check_game_over()
        message = f"rolled {roll.total}"
        if self._game_over:
            message = f"{message}; game over ({self._reason})"
        return RollOutcome(ok=True, message=message, view=self.snapshot())

    def _check_game_over(self) -> None:
        """Apply the termination gates with BUST -> GOAL -> MAX-ROLLS precedence.

        The MAX-ROLLS gate is skipped entirely when ``config.max_rolls is None``
        (uncapped interactive play): such a game ends only on bust or, if set, the
        win goal.

        Bust is judged on NET WORTH (``self._table.bankroll``), NOT the wallet
        figure the view shows: chips resting on the felt are still yours, so you
        are only bust when your total position is gone, not when your cash is
        merely committed to live bets.
        """
        bankroll = self._table.bankroll
        config = self._config
        if bankroll <= config.loss_limit:
            self._game_over = True
            self._reason = "bust"
        elif config.win_goal is not None and bankroll >= config.win_goal:
            self._game_over = True
            self._reason = "goal reached"
        elif config.max_rolls is not None and self._rolls_used >= config.max_rolls:
            self._game_over = True
            self._reason = "max rolls reached"


# --- data-driven coaching hints ---------------------------------------------

# Concrete bet-class names (``type(bet).__name__``) grouped by role, so the hint
# predicates read as set-membership tests instead of scattered string literals.
_LINE_BET_NAMES = frozenset({"PassLine", "DontPass", "ComeBet", "DontCome"})
_ODDS_BET_NAMES = frozenset({"TakeOdds", "LayOdds"})

# game_over_reason -> the one-line coaching message shown once a game has ended.
_GAME_OVER_MESSAGES = {
    "bust": "Game over — you busted. Start a new game to play again.",
    "goal reached": "Game over — you hit your win goal!",
    "max rolls reached": "Game over — out of rolls. Start a new game to play again.",
}


def _is_come_out(view: GameView) -> bool:
    """True while the table is on the come-out (no point established)."""
    return view.phase == Phase.COME_OUT.value


def _has_place_bet_off(view: GameView) -> bool:
    """True iff any active bet is a Place bet currently switched OFF.

    Place bets default to OFF on the come-out, where they neither win nor lose;
    flagging this lets the coach warn a player who may expect them to act.
    """
    return any(type(bet).__name__ == "PlaceBet" and not bet.working for bet in view.active_bets)


def _odds_prompt_applies(view: GameView) -> bool:
    """True iff odds are placeable and a line bet lacks any backing odds bet.

    Requires the engine's own ``odds_available`` gate (a point is on), at least
    one line bet to back, and no odds bet already down.
    """
    if not view.odds_available:
        return False
    names = {type(bet).__name__ for bet in view.active_bets}
    return bool(names & _LINE_BET_NAMES) and not (names & _ODDS_BET_NAMES)


def _always(_view: GameView) -> bool:
    """Always-true predicate for the point-generic default rule."""
    return True


def _place_off_on_come_out(view: GameView) -> bool:
    """True on the come-out with a non-working Place bet down."""
    return _is_come_out(view) and _has_place_bet_off(view)


def _render_game_over(view: GameView) -> str:
    """Map ``game_over_reason`` to its message, defaulting for the unexpected."""
    return _GAME_OVER_MESSAGES.get(
        view.game_over_reason or "",
        "Game over. Start a new game to play again.",
    )


def _render_place_off(_view: GameView) -> str:
    """Warn that Place bets are OFF on the come-out roll."""
    return (
        "Heads up: place bets are OFF on the come-out roll — they don't win "
        "or lose until a point is set."
    )


def _render_come_out(view: GameView) -> str:
    """Explain how a Pass line resolves on the come-out roll (variant-aware)."""
    if view.variant == "crapless":
        return (
            "Come-out: a Pass line wins on 7; any other number becomes your "
            "point (nothing craps out)."
        )
    return "Come-out roll: a Pass line wins on 7 or 11 and loses on 2, 3, or 12."


def _render_odds_prompt(view: GameView) -> str:
    """Prompt the player to back a naked line bet with free odds."""
    return (
        f"Point is {view.point}. You can back your line bet with free odds — "
        "the only zero-house-edge bet in craps."
    )


def _render_point_generic(view: GameView) -> str:
    """The catch-all point hint: make the point before a seven."""
    return f"Point is {view.point}: roll it again before a 7 to win your Pass line."


#: Ordered ``(predicate, render)`` coaching rules; FIRST match wins.
#:
#: Precedence: game-over first (nothing else matters once a game ends), then the
#: come-out warnings/explainer, then the odds prompt, and finally the always-true
#: point-generic default. Because the come-out explainer (:func:`_is_come_out`)
#: catches every come-out view, reaching the final :func:`_always` rule implies a
#: point is on, so the table is exhaustive over every possible view.
_HINT_RULES: list[tuple[Callable[[GameView], bool], Callable[[GameView], str]]] = [
    (lambda v: v.game_over, _render_game_over),
    (_place_off_on_come_out, _render_place_off),
    (_is_come_out, _render_come_out),
    (_odds_prompt_applies, _render_odds_prompt),
    (_always, _render_point_generic),
]


def coaching_hint(view: GameView) -> str:
    """Return one short, single-line coaching hint for the current game moment.

    Walks the module-level :data:`_HINT_RULES` table in precedence order and
    returns the rendered message of the FIRST rule whose predicate matches
    ``view``. The rules are exhaustive: the come-out explainer catches every
    come-out view and the final always-true rule catches every point view, so a
    match is guaranteed.

    Args:
        view: An immutable :class:`GameView` snapshot of the game.

    Returns:
        A single-line hint string tailored to ``view``'s phase, bets, and
        game-over state.
    """
    render = next(render for predicate, render in _HINT_RULES if predicate(view))
    return render(view)
