"""Single-session runner: a :class:`Table` plus the ``run_session`` loop.

This module threads the three engine pieces that until now stood alone -- the
dice source, the :class:`~craps_engine.state.GameState` phase machine, and the
live :class:`~craps_engine.bets.base.Bet` objects -- into one deterministic play
loop, accumulating a per-session bankroll trajectory.

ROLL ORDERING (the #1 gotcha -- ``run_session`` follows it EXACTLY)
-------------------------------------------------------------------
Every bet's ``resolve`` reads the table phase/point, so the order in which we
resolve versus advance the phase machine is load-bearing. Per roll we:

1. let the strategy place bets,
2. roll the dice,
3. resolve EVERY live bet against the PRE-roll state (do NOT ``state.apply``
   first -- a Pass Line riding point 4 must still see POINT/4 when the 7 lands),
4. ``advance`` each bet (its sanctioned self-mutation hook),
5. drop the bets that no longer remain on the table,
6. ONLY THEN ``state.apply`` the rolled total to move the phase machine,
7. record the post-roll bankroll and check termination.

Steps 3-6 -- the load-bearing settlement -- live in :meth:`Table.settle`, which
``run_session`` calls once per roll; steps 1, 2, and 7 stay in the loop.
Resolving before applying is what keeps ``resolve`` a pure read of the current
phase; applying after is what readies the machine for the NEXT roll.

NET-WORTH ACCOUNTING (a documented simplification)
--------------------------------------------------
``bankroll`` is NET WORTH: free cash PLUS chips currently working on the table.
Each roll we simply do ``bankroll += sum(resolution.delta)``, reusing the signed
``delta`` convention from :class:`~craps_engine.bets.base.Resolution` verbatim --
there is deliberately NO placement deduction when a bet goes down and NO
stake-return bookkeeping when it comes off. Because winnings exclude the stake
and a standing stake never leaves net worth, the running sum of deltas tracks net
worth correctly without that bookkeeping. Bet sizing is assumed affordable (no
free-cash constraint) -- a future refinement.

``peak``/``trough`` span the WHOLE trajectory INCLUDING the starting bankroll
(both are seeded with it before the loop), whereas ``history`` holds ONLY the
post-roll bankrolls -- exactly one entry per executed roll.
"""

from __future__ import annotations

from dataclasses import dataclass
from fractions import Fraction
from typing import TYPE_CHECKING, Protocol, TypedDict, runtime_checkable

from craps_engine.money import FractionPayload, serialize_fraction
from craps_engine.state import GameState

if TYPE_CHECKING:
    from craps_engine.bets.base import Bet, Resolution
    from craps_engine.dice import Dice, DiceRoll
    from craps_engine.state import PhaseTransition


@runtime_checkable
class Strategy(Protocol):
    """A betting strategy: the policy that places wagers before each roll.

    Declared HERE, alongside its sole consumer ``run_session``, rather than with
    the concrete strategies (which arrive in a later task) so those concrete
    types can depend on this module without a circular import. Runtime-checkable
    so a session can assert an object satisfies the contract via ``isinstance``.
    """

    def place_bets(self, table: Table) -> None:
        """Add wagers to ``table`` (via :meth:`Table.add_bet`) before the next roll."""
        ...


@dataclass(frozen=True)
class SessionConfig:
    """Immutable knobs for one session run.

    Frozen so a config is a safe value to share across runs / log. ``win_goal``
    is optional (``None`` means "no goal, run to ``max_rolls``"); ``loss_limit``
    is the bankroll floor at or below which the session busts (default 0).
    """

    #: Bankroll the shooter starts with (also seeds peak/trough).
    starting_bankroll: Fraction
    #: Hard cap on the number of rolls executed; ``None`` means uncapped
    #: (interactive play only). Batch runners MUST pass an int -- ``run_session``
    #: fails fast on ``None``.
    max_rolls: int | None = None
    #: Bankroll at/above which the session stops a winner, or ``None`` for none.
    win_goal: Fraction | None = None
    #: Bankroll floor; reaching it (``<=``) busts the session.
    loss_limit: Fraction = Fraction(0)


class SessionResultPayload(TypedDict):
    """Serialized shape of a :class:`SessionResult`.

    Every monetary field is a non-percent :class:`~craps_engine.money.FractionPayload`
    (``history`` is a list of them); ``rolls`` is a plain int and the two flags
    are plain bools, so any UI / Monte-Carlo layer consumes one fixed shape.
    """

    ending_bankroll: FractionPayload
    peak: FractionPayload
    trough: FractionPayload
    rolls: int
    busted: bool
    hit_goal: bool
    history: list[FractionPayload]


@dataclass
class SessionResult:
    """The outcome record for one completed session.

    Built up front by ``run_session`` and returned once the loop stops. See the
    module docstring for the peak/trough-include-start and history-is-post-roll
    conventions.
    """

    #: Bankroll when the session ended.
    ending_bankroll: Fraction
    #: Highest bankroll seen over the trajectory (INCLUDING the start).
    peak: Fraction
    #: Lowest bankroll seen over the trajectory (INCLUDING the start).
    trough: Fraction
    #: Number of rolls actually executed.
    rolls: int
    #: True iff the session ended by hitting the loss limit.
    busted: bool
    #: True iff the session ended by reaching the win goal.
    hit_goal: bool
    #: Post-roll bankroll after each executed roll (one entry per roll).
    history: list[Fraction]

    def to_dict(self) -> SessionResultPayload:
        """Serialize to a UI/MC-friendly shape.

        Every Fraction is serialized as MONEY (``as_percent=False``) so the
        exact/float/display payload reads as a plain amount; ``history`` becomes a
        parallel list of those payloads, and ints/bools pass through unchanged.
        """
        return {
            "ending_bankroll": serialize_fraction(self.ending_bankroll, as_percent=False),
            "peak": serialize_fraction(self.peak, as_percent=False),
            "trough": serialize_fraction(self.trough, as_percent=False),
            "rolls": self.rolls,
            "busted": self.busted,
            "hit_goal": self.hit_goal,
            "history": [serialize_fraction(b, as_percent=False) for b in self.history],
        }


@dataclass(frozen=True)
class SettleResult:
    """Outcome of settling one already-rolled DiceRoll against the table.

    ``settled`` pairs each bet that was live at roll time with its Resolution
    (in resolution order); ``transition`` is the PhaseTransition returned by
    advancing the phase machine AFTER all bets resolved.
    """

    settled: list[tuple[Bet, Resolution]]
    transition: PhaseTransition


class Table:
    """The mutable live state of a session: bankroll, phase machine, and bets.

    A plain mutable class (not a frozen value object) because a session mutates
    all three fields as play proceeds. The bet list is private so the only ways
    to touch it are :meth:`add_bet` (append) and :meth:`active_bets` (a read-only
    snapshot); :meth:`settle` owns the per-roll survivor swap internally.
    """

    def __init__(self, bankroll: Fraction, state: GameState | None = None) -> None:
        """Create a table, defaulting a fresh come-out :class:`GameState`."""
        #: Net worth: free cash plus chips working on the felt.
        self.bankroll = bankroll
        #: The table-level come-out / point phase machine.
        self.state = state if state is not None else GameState()
        #: Live wagers; mutated only via add_bet / Table.settle's survivor swap.
        self._bets: list[Bet] = []

    def add_bet(self, bet: Bet) -> None:
        """Put a wager on the table for the upcoming roll."""
        self._bets.append(bet)

    def active_bets(self) -> list[Bet]:
        """Return a COPY of the live bets so callers cannot mutate the internals."""
        return list(self._bets)

    def remove_bet(self, bet_id: str) -> Bet | None:
        """Take the FIRST bet with ``bet_id`` off the table, returning it or None.

        A practice-friendly "undo a mis-click": drops the first live bet whose
        ``id`` matches and returns it, or returns ``None`` when no such id is on
        the table. There is deliberately NO contract-bet locking -- any bet may
        come down at any time.

        Removing a bet NEVER moves ``bankroll``. Under the net-worth accounting
        (see the module docstring) a standing stake is already counted as net
        worth and was never deducted from the bankroll when it went down, so
        taking it back off cannot change the bankroll either.
        """
        for index, bet in enumerate(self._bets):
            if bet.id == bet_id:
                return self._bets.pop(index)
        return None

    def settle(self, roll: DiceRoll) -> SettleResult:
        """Resolve every live bet against the PRE-roll state, then advance the machine.

        Runs the load-bearing per-roll ordering on an ALREADY-rolled DiceRoll:
        resolve all bets vs the current phase (summing signed deltas into
        ``bankroll``) -> advance each bet -> prune non-survivors -> apply the
        rolled total to the phase machine. Returns the settled (bet, resolution)
        pairs and the resulting PhaseTransition. Placing bets and rolling happen
        OUTSIDE this method (a human or a strategy interleaves between them).
        """
        # 3. Resolve EVERY live bet against the PRE-roll state (do not apply the
        #    phase machine first -- bets must read the current phase/point).
        settled: list[tuple[Bet, Resolution]] = []
        for bet in self.active_bets():
            resolution = bet.resolve(roll, self.state)
            self.bankroll += resolution.delta
            settled.append((bet, resolution))

        # 4. Let each bet apply its own per-roll transition (advance hook).
        for bet, resolution in settled:
            bet.advance(roll, resolution)

        # 5. Keep only the bets that remain on the table after this roll.
        self._bets = [bet for bet, resolution in settled if bet.remains_on_table(resolution, roll)]

        # 6. ONLY NOW advance the phase machine, readying it for the next roll.
        transition = self.state.apply(roll.total)

        return SettleResult(settled=settled, transition=transition)


def run_session(dice: Dice, strategy: Strategy, config: SessionConfig) -> SessionResult:
    """Play one deterministic session and return its :class:`SessionResult`.

    Drives the strict per-roll ordering documented at the module level
    (place -> roll -> resolve PRE-apply -> advance -> prune -> apply -> record)
    and the net-worth ``delta`` accounting. Peak/trough are seeded with the
    starting bankroll so they span the full trajectory; ``history`` collects only
    post-roll bankrolls. Termination precedence is BUST FIRST, then goal; the loop
    never exceeds ``config.max_rolls`` rolls.

    Fails fast with ``ValueError`` when ``config.max_rolls is None``: an uncapped
    config is legal for interactive play only, and a batch run without a cap would
    loop forever. Interactive play uses :class:`~craps_engine.play.PlayController`.
    """
    if config.max_rolls is None:
        msg = (
            "run_session requires a finite max_rolls; None (uncapped) is for "
            "interactive play only and would loop forever in a batch run"
        )
        raise ValueError(msg)

    table = Table(config.starting_bankroll)

    # Seed peak/trough with the start so the trajectory INCLUDES the opening
    # bankroll, even on a session that immediately bets and loses.
    peak = config.starting_bankroll
    trough = config.starting_bankroll
    history: list[Fraction] = []
    rolls = 0
    busted = False
    hit_goal = False

    for _ in range(config.max_rolls):
        # 1. Strategy stakes its wagers for THIS roll.
        strategy.place_bets(table)

        # 2. Roll the dice.
        roll = dice.roll()

        # 3-6. Settle the roll: resolve PRE-apply -> advance -> prune -> apply.
        #    Table.settle owns this load-bearing ordering; the returned
        #    SettleResult is ignored here (bankroll is read off the table).
        table.settle(roll)

        # 7. Record the post-roll bankroll and update the trajectory extremes.
        history.append(table.bankroll)
        peak = max(peak, table.bankroll)
        trough = min(trough, table.bankroll)
        rolls += 1

        # Termination precedence: BUST first, then goal.
        if table.bankroll <= config.loss_limit:
            busted = True
            break
        if config.win_goal is not None and table.bankroll >= config.win_goal:
            hit_goal = True
            break

    return SessionResult(
        ending_bankroll=table.bankroll,
        peak=peak,
        trough=trough,
        rolls=rolls,
        busted=busted,
        hit_goal=hit_goal,
        history=history,
    )
