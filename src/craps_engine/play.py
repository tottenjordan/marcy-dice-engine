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

from dataclasses import dataclass
from typing import TYPE_CHECKING, TypedDict

from craps_engine.money import serialize_fraction
from craps_engine.session import SessionConfig, Table
from craps_engine.specs import BetSpec, build_bet, parse_bet_spec
from craps_engine.state import Phase

if TYPE_CHECKING:
    from fractions import Fraction

    from craps_engine.bets.base import Bet, BetPayload, Resolution, ResolutionPayload
    from craps_engine.dice import Dice, DiceRoll, DiceRollPayload
    from craps_engine.money import FractionPayload

# The odds kinds that are legal only once a point is established.
_ODDS_KINDS = frozenset({"take", "lay"})


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
    rolls_used: int
    rolls_left: int
    game_over: bool
    game_over_reason: str | None
    odds_available: bool


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
    #: Current net-worth bankroll (free cash plus working chips).
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
    #: Number of rolls executed so far.
    rolls_used: int
    #: Rolls remaining before the max-rolls cap (``max_rolls - rolls_used``).
    rolls_left: int
    #: Whether the game has ended.
    game_over: bool
    #: Why the game ended, or ``None`` while it is live.
    game_over_reason: str | None
    #: True iff odds may be placed now (i.e. the phase is POINT).
    odds_available: bool

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
            "rolls_used": self.rolls_used,
            "rolls_left": self.rolls_left,
            "game_over": self.game_over,
            "game_over_reason": self.game_over_reason,
            "odds_available": self.odds_available,
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
        self._table = Table(config.starting_bankroll)
        #: Monotonic id source so every placed bet gets a distinct id.
        self._counter = 0
        self._rolls_used = 0
        self._last_roll: DiceRoll | None = None
        self._last_outcomes: list[Resolution] = []
        self._game_over = False
        self._reason: str | None = None

    def snapshot(self) -> GameView:
        """Build a :class:`GameView` from the current table/config/roll state."""
        bankroll = self._table.bankroll
        starting = self._config.starting_bankroll
        phase = self._table.state.phase
        return GameView(
            starting_bankroll=starting,
            bankroll=bankroll,
            running_net=bankroll - starting,
            phase=phase.value,
            point=self._table.state.point,
            active_bets=self._table.active_bets(),
            last_roll=self._last_roll,
            last_outcomes=list(self._last_outcomes),
            rolls_used=self._rolls_used,
            rolls_left=self._config.max_rolls - self._rolls_used,
            game_over=self._game_over,
            game_over_reason=self._reason,
            odds_available=phase is Phase.POINT,
        )

    def place_bet(self, spec: BetSpec) -> PlaceOutcome:
        """Place one validated :class:`BetSpec`; NEVER raises.

        Illegal placements are rejected with ``ok=False`` and a message rather
        than an exception: the game being over, odds attempted off a point, or
        odds that do not back the current point. On success the bet is added to
        the table with a freshly-minted unique id.
        """
        if self._game_over:
            return PlaceOutcome(
                ok=False,
                message=f"game over ({self._reason})",
                view=self.snapshot(),
            )

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

    def _reject_illegal_odds(self, spec: BetSpec) -> PlaceOutcome | None:
        """Return a rejection for illegal take/lay odds, else ``None``.

        Odds are legal only while a point is established, and only when they back
        that exact point. Returns ``None`` when the odds bet is legal.
        """
        if self._table.state.phase is not Phase.POINT:
            return PlaceOutcome(
                ok=False,
                message="odds require an established point",
                view=self.snapshot(),
            )
        point = self._table.state.point
        if spec.number != point:
            return PlaceOutcome(
                ok=False,
                message=f"odds must back the current point ({point})",
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
        self._rolls_used += 1

        self._check_game_over()
        message = f"rolled {roll.total}"
        if self._game_over:
            message = f"{message}; game over ({self._reason})"
        return RollOutcome(ok=True, message=message, view=self.snapshot())

    def _check_game_over(self) -> None:
        """Apply the termination gates with BUST -> GOAL -> MAX-ROLLS precedence."""
        bankroll = self._table.bankroll
        config = self._config
        if bankroll <= config.loss_limit:
            self._game_over = True
            self._reason = "bust"
        elif config.win_goal is not None and bankroll >= config.win_goal:
            self._game_over = True
            self._reason = "goal reached"
        elif self._rolls_used >= config.max_rolls:
            self._game_over = True
            self._reason = "max rolls reached"
