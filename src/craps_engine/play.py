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
    from collections.abc import Callable
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
    rolls_left: int | None
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
    #: Rolls remaining before the max-rolls cap (``max_rolls - rolls_used``), or
    #: ``None`` when uncapped (``config.max_rolls is None``).
    rolls_left: int | None
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
        max_rolls = self._config.max_rolls
        rolls_left = None if max_rolls is None else max_rolls - self._rolls_used
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
            rolls_left=rolls_left,
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
        """Apply the termination gates with BUST -> GOAL -> MAX-ROLLS precedence.

        The MAX-ROLLS gate is skipped entirely when ``config.max_rolls is None``
        (uncapped interactive play): such a game ends only on bust or, if set, the
        win goal.
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


def _render_come_out(_view: GameView) -> str:
    """Explain how a Pass line resolves on the come-out roll."""
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
