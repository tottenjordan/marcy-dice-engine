"""Dual-lens analysis of a SET of active bets: :class:`PortfolioAnalyzer`.

A single bet's economics are easy to quote; a *portfolio* of bets that interact
(a hedge, a pressed line bet, a Don't backed by lays) needs two DIFFERENT, and
deliberately non-equivalent, views to be understood. This module is math-critical:
every value is an exact :class:`~fractions.Fraction`, no floats ever enter the
arithmetic (they appear only at the serialization boundary, via
:func:`~craps_engine.money.serialize_fraction`).

The two lenses
--------------
* **LENS A -- ``single_roll_ev`` (current-state / variance view).** The exact
  probability-weighted net bankroll change of ONE more roll *from the current
  phase and point*. This answers "what does the next roll do, on average, given
  where we are RIGHT NOW?". It is a conditional, short-horizon number that
  reflects the established point.

* **LENS B -- ``house_drag`` (long-run cost view).** The sum over all bets of
  ``stake x per-resolution house edge``, returned as a POSITIVE cost (positive =
  expected loss to the house over the bet's full life). This is the structural,
  edge-paid-up-front number; it does NOT depend on the current phase.

Why the two lenses tell different stories (the whole point of the tool)
-----------------------------------------------------------------------
In the worked hedge example (Don't Pass 10 + Place 6 / 8 of 6, point 4) the
``single_roll_ev`` is POSITIVE (Fraction(28, 36)) even though the ``house_drag``
is a POSITIVE COST (Fraction(7, 22)). There is no contradiction: a Don't-Pass
bettor *paid* the house edge on the come-out (the bar-12 push is where that edge
lives) and is, AFTER a point is established, the statistical FAVORITE -- there
are more ways to roll a 7 than to make any single point. So conditioned on
already being on the point, the next roll favors the player (Lens A is positive),
while the bet considered over its whole life still carries a house edge
(Lens B is a positive cost). A tool that only reported one of these would lie by
omission; reporting BOTH is the design.
"""

from __future__ import annotations

from fractions import Fraction
from typing import TYPE_CHECKING, TypedDict

from craps_engine.bets.come import ComeBet, DontCome
from craps_engine.bets.line import DontPass, PassLine
from craps_engine.bets.odds import LayOdds, TakeOdds
from craps_engine.bets.place import PlaceBet
from craps_engine.dice import DiceRoll
from craps_engine.money import FractionPayload, serialize_fraction
from craps_engine.registry import REGISTRY, TOTAL_PROBABILITY, place_spec

if TYPE_CHECKING:
    from collections.abc import Sequence

    from craps_engine.bets.base import Bet, BetPayload
    from craps_engine.state import GameState

# Inclusive bounds on a two-die total -- the totals the matrix spans (2..12).
_MIN_TOTAL = 2
_MAX_TOTAL = 7  # The pivot used by the representative-roll helper (see below).
_MAX_DIE_TOTAL = 12


class PortfolioReport(TypedDict):
    """Serialized bundle a future UI / Monte-Carlo layer consumes.

    ``matrix`` maps each total (2..12) to a serialized MONEY Fraction (the net
    delta for that total). ``single_roll_ev`` and ``house_drag`` are serialized
    MONEY scalars (``as_percent=False``). ``bets`` is the per-bet ``to_dict()``
    list so the exact portfolio composition round-trips alongside its analysis.
    """

    matrix: dict[int, FractionPayload]
    single_roll_ev: FractionPayload
    house_drag: FractionPayload
    bets: list[BetPayload]


def _representative_roll(total: int) -> DiceRoll:
    """Build ANY valid :class:`DiceRoll` summing to ``total``.

    A bet's resolution depends only on the dice TOTAL, never the specific pip
    combination, so for the payout matrix we just need one representative roll
    per total. To keep both pips inside 1..6:

    * for ``total <= 7`` use ``(total - 1, 1)`` -- the first die is 1..6, the
      second is a constant 1;
    * for ``total > 7`` use ``(6, total - 6)`` -- the first die is a constant 6,
      the second is 1..6.

    The two branches together cover 2..12 with every die in range.
    """
    if total <= _MAX_TOTAL:
        return DiceRoll(total - 1, 1)
    return DiceRoll(6, total - 6)


class PortfolioAnalyzer:
    """Evaluate a set of active bets collectively through two lenses.

    See the module docstring for the full dual-lens rationale. ``__init__``
    stores a defensive COPY of the bets so later mutation of the caller's
    sequence cannot change the analyzed portfolio. An empty portfolio is valid
    and degenerates cleanly to all-zero results.
    """

    def __init__(self, bets: Sequence[Bet]) -> None:
        """Store a defensive copy of ``bets`` (empty portfolio allowed)."""
        # Copy into a fresh list so the analyzer owns its view of the portfolio.
        self._bets: list[Bet] = list(bets)

    def net_payout_matrix(self, state: GameState) -> dict[int, Fraction]:
        """Net signed bankroll delta per dice total (2..12) for the next roll.

        For each total we build one representative roll (the outcome depends only
        on the total) and SUM ``bet.resolve(roll, state).delta`` across every
        bet. The result is the table the EV lens weights by probability and a UI
        can render directly.

        STATE PURITY: every concrete bet's ``resolve`` only READS the phase and
        point (verified against ``bets/line.py``, ``bets/place.py``,
        ``bets/odds.py`` -- none call ``state.apply`` or otherwise mutate it), so
        a single shared ``state`` is safe to pass for all 11 totals. We never
        mutate ``state`` here.
        """
        matrix: dict[int, Fraction] = {}
        for total in range(_MIN_TOTAL, _MAX_DIE_TOTAL + 1):
            roll = _representative_roll(total)
            # Exact running sum starts at Fraction(0) so an empty portfolio (or a
            # total nothing acts on) yields exactly Fraction(0), not int 0.
            net = Fraction(0)
            for bet in self._bets:
                net += bet.resolve(roll, state).delta
            matrix[total] = net
        return matrix

    def single_roll_ev(self, state: GameState) -> Fraction:
        """LENS A: exact probability-weighted net delta of the next roll.

        ``sum(P(total) * net_delta(total))`` over totals 2..12, using the exact
        ``Fraction`` probabilities from :data:`registry.TOTAL_PROBABILITY`. This
        is the CURRENT-STATE view -- it is conditioned on the phase/point in
        ``state`` -- and can be positive even when :meth:`house_drag` is a
        positive cost (see the module docstring's Don't-Pass insight).
        """
        matrix = self.net_payout_matrix(state)
        ev = Fraction(0)
        for total, delta in matrix.items():
            ev += TOTAL_PROBABILITY[total] * delta
        return ev

    def house_drag(self) -> Fraction:
        """LENS B: total long-run expected COST of the portfolio.

        Returns ``sum(bet.amount * house_edge(bet))`` over all bets as a POSITIVE
        Fraction. SIGN CONVENTION: positive = expected loss to the house (a
        cost/drag on the bankroll over the bet's full life). This is the
        structural edge-paid number and does NOT depend on the table phase.
        """
        drag = Fraction(0)
        for bet in self._bets:
            drag += bet.amount * self._house_edge(bet)
        return drag

    @staticmethod
    def _house_edge(bet: Bet) -> Fraction:
        """Per-resolution house edge for ``bet``, dispatched by concrete type.

        * :class:`PassLine` -> 7/495, :class:`DontPass` -> 3/220 (from REGISTRY).
        * :class:`ComeBet` -> 7/495 (Pass edge), :class:`DontCome` -> 3/220
          (Don't Pass edge): a come-family bet is mechanically a travelling line
          bet, so it carries the same per-resolution edge as its line mirror.
        * :class:`PlaceBet` -> ``place_spec(bet.number).house_edge``.
        * :class:`TakeOdds` / :class:`LayOdds` -> Fraction(0) (free odds carry no
          edge).

        Any other :class:`Bet` subtype raises :class:`TypeError` naming the type:
        for a MONEY tool, silently defaulting an unrecognized bet to zero drag
        would under-count cost, so we fail fast instead.
        """
        if isinstance(bet, PassLine):
            return REGISTRY["pass_line"].house_edge
        if isinstance(bet, DontPass):
            return REGISTRY["dont_pass"].house_edge
        if isinstance(bet, ComeBet):
            # A come bet mirrors the Pass Line, so it carries the Pass edge.
            return REGISTRY["pass_line"].house_edge
        if isinstance(bet, DontCome):
            # A don't-come bet mirrors Don't Pass, so it carries that edge.
            return REGISTRY["dont_pass"].house_edge
        if isinstance(bet, PlaceBet):
            return place_spec(bet.number).house_edge
        if isinstance(bet, (TakeOdds, LayOdds)):
            # Free odds pay true odds: exactly zero house edge.
            return Fraction(0)
        msg = f"unsupported bet type for house-edge drag: {type(bet).__name__}"
        raise TypeError(msg)

    def report(self, state: GameState) -> PortfolioReport:
        """Serializable bundle (matrix + both lenses + per-bet composition).

        Every Fraction is serialized as MONEY (``as_percent=False``) so the
        exact/float/display payload reads as a plain amount, not a percentage,
        matching the convention used by the bet/resolution serializers.
        """
        matrix = self.net_payout_matrix(state)
        return {
            "matrix": {
                total: serialize_fraction(delta, as_percent=False)
                for total, delta in matrix.items()
            },
            "single_roll_ev": serialize_fraction(self.single_roll_ev(state), as_percent=False),
            "house_drag": serialize_fraction(self.house_drag(), as_percent=False),
            "bets": [bet.to_dict() for bet in self._bets],
        }
