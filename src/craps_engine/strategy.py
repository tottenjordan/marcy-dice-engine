"""Concrete starter betting strategies satisfying the ``Strategy`` Protocol.

The structural :class:`~craps_engine.session.Strategy` Protocol -- a single
``place_bets(self, table) -> None`` -- lives in :mod:`craps_engine.session`,
alongside its consumer ``run_session``, to avoid a circular import. The concrete
strategies here conform STRUCTURALLY; they do not inherit it.

THE IDEMPOTENCY CONTRACT (load-bearing -- read before editing)
--------------------------------------------------------------
``run_session`` calls ``place_bets`` BEFORE EVERY roll, not once per round. A
strategy must therefore be safe to invoke repeatedly against the same live table:
it places a wager ONLY when the current phase warrants it AND no live bet already
carries that wager's stable id. Each strategy below uses fixed ids (``pass``,
``odds``, ``dp``, ``p6``, ``p8``) and guards every ``add_bet`` with an
"id-not-already-active" check, so re-invocation never stacks duplicate wagers.

WHY EACH STRATEGY PLACES WHEN IT DOES
-------------------------------------
* A flat line bet (Pass / Don't Pass) is placed on the COME-OUT, because that is
  the only phase a fresh line bet may be made; once down it rides the round.
* Free odds back an established point, so they are placed on the POINT phase only
  (and only behind an existing flat bet) -- mirroring real table rules where odds
  are off on the come-out.
* The hedging place bets (6 and 8) are added on the POINT phase: they win on the
  very numbers the Don't bettor fears, smoothing the round's swings.
"""

from __future__ import annotations

from fractions import Fraction
from typing import TYPE_CHECKING

from craps_engine.bets.line import DontPass, PassLine
from craps_engine.bets.odds import TakeOdds
from craps_engine.bets.place import PlaceBet
from craps_engine.state import Phase

if TYPE_CHECKING:
    from craps_engine.session import Table


def _has_bet(table: Table, bet_id: str) -> bool:
    """Whether a live bet on ``table`` already carries ``bet_id``.

    The single idempotency primitive every strategy guards its ``add_bet`` with,
    so re-invoking ``place_bets`` across rolls never stacks a duplicate wager.
    """
    return any(bet.id == bet_id for bet in table.active_bets())


class PassLineStrategy:
    """Place a single flat Pass Line bet on each come-out.

    The simplest right-way strategy: on the COME-OUT phase, if no ``pass`` bet is
    already live, stake one :class:`~craps_engine.bets.line.PassLine` at the
    configured unit. It does nothing on the POINT phase (a flat line bet can only
    be made on the come-out) and nothing when a ``pass`` bet already rides -- the
    twin guards that make repeated ``place_bets`` calls idempotent.
    """

    def __init__(self, unit: Fraction | int = 10) -> None:
        """Store the flat unit, normalizing an ``int`` to an exact ``Fraction``."""
        #: The flat Pass Line stake (exact Fraction for the engine's math).
        self.unit: Fraction = Fraction(unit)

    def place_bets(self, table: Table) -> None:
        """Add a ``pass`` PassLine on a fresh come-out; otherwise do nothing."""
        if table.state.phase is Phase.COME_OUT and not _has_bet(table, "pass"):
            table.add_bet(PassLine("pass", self.unit))


class PassLineOddsStrategy(PassLineStrategy):
    """Pass Line, then back an established point with free odds.

    Extends :class:`PassLineStrategy` by composition-via-``super()``: it first
    applies the flat pass-line rule, then -- once a point is set and a ``pass``
    bet is live -- adds a single :class:`~craps_engine.bets.odds.TakeOdds` (id
    ``odds``) behind it. Subclassing keeps the come-out behavior in one place;
    both branches stay idempotent through the ``_has_bet`` guard.

    ODDS SIZING: the odds stake equals ``unit`` (1x the flat bet) -- a simple,
    declarative default. Real tables cap odds relative to the flat bet ("3-4-5x"
    max odds), but that is a future TABLE-RULES concern already documented in
    :mod:`craps_engine.bets.odds` (``MAX_ODDS_MULTIPLIER``), not enforced here.
    """

    def place_bets(self, table: Table) -> None:
        """Apply the pass-line rule, then back a set point with ``odds``."""
        super().place_bets(table)
        state = table.state
        if (
            state.phase is Phase.POINT
            and state.point is not None
            and _has_bet(table, "pass")
            and not _has_bet(table, "odds")
        ):
            table.add_bet(TakeOdds("odds", state.point, self.unit))


class DontPassPlaceStrategy:
    """The hedged Don't-Pass showcase: DP line plus Place 6 and Place 8.

    Reproduces the canonical ``examples/hedged_dp_place68.py`` portfolio. On the
    COME-OUT it stakes a :class:`~craps_engine.bets.line.DontPass` (id ``dp``);
    once a point is set it adds working :class:`~craps_engine.bets.place.PlaceBet`
    wagers on 6 (id ``p6``) and 8 (id ``p8``) -- the numbers that hedge the Don't
    bettor's seven-out exposure. Defaults reproduce the showcase EXACTLY:
    ``line_unit=10``, ``place_unit=6``. Every ``add_bet`` is guarded by
    ``_has_bet`` so repeated calls across rolls never stack duplicates.
    """

    def __init__(
        self,
        line_unit: Fraction | int = 10,
        place_unit: Fraction | int = 6,
    ) -> None:
        """Store the line and place units, normalizing ``int`` to ``Fraction``.

        Defaults (10 / 6) reproduce the showcase: ``DontPass("dp", 10)`` plus
        ``PlaceBet`` 6 and 8 of 6 each.
        """
        #: The Don't Pass line stake (exact Fraction).
        self.line_unit: Fraction = Fraction(line_unit)
        #: The per-number place stake for 6 and 8 (exact Fraction).
        self.place_unit: Fraction = Fraction(place_unit)

    def place_bets(self, table: Table) -> None:
        """Stake ``dp`` on come-out; add working ``p6``/``p8`` on the point."""
        if table.state.phase is Phase.COME_OUT:
            if not _has_bet(table, "dp"):
                table.add_bet(DontPass("dp", self.line_unit))
            return
        # POINT phase: lay the two hedging place bets, working through come-outs.
        if not _has_bet(table, "p6"):
            table.add_bet(PlaceBet("p6", 6, self.place_unit, working=True))
        if not _has_bet(table, "p8"):
            table.add_bet(PlaceBet("p8", 8, self.place_unit, working=True))
