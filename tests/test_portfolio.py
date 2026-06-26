"""Tests for :class:`~craps_engine.portfolio.PortfolioAnalyzer`.

Written TDD-first. The analyzer evaluates a SET of active bets collectively
through two complementary lenses:

* ``single_roll_ev`` (LENS A) -- the current-state/variance view: the exact
  probability-weighted net delta of one more roll from the CURRENT phase/point.
* ``house_drag`` (LENS B) -- the long-run cost view: the sum of each bet's
  stake times its per-resolution house edge, returned as a POSITIVE cost.

The headline oracle is the worked HEDGE example (Don't Pass 10 + Place 6 / 8
of 6 each, point 4), which is asserted to the exact Fraction in every lens.
"""

from fractions import Fraction

import pytest

from craps_engine.bets.base import Bet, Resolution, ResolutionStatus
from craps_engine.bets.line import DontPass, PassLine
from craps_engine.bets.odds import TakeOdds
from craps_engine.bets.place import PlaceBet
from craps_engine.dice import DiceRoll
from craps_engine.portfolio import PortfolioAnalyzer
from craps_engine.state import GameState, Phase


def _hedge() -> PortfolioAnalyzer:
    """The worked hedge portfolio: Don't Pass 10 plus Place 6 / 8 of 6 each."""
    return PortfolioAnalyzer(
        [
            DontPass("dp", Fraction(10)),
            PlaceBet("p6", 6, Fraction(6), working=True),
            PlaceBet("p8", 8, Fraction(6), working=True),
        ]
    )


def _point4() -> GameState:
    """A GameState on POINT with point 4 (matching the worked example)."""
    s = GameState()
    s.apply(4)
    return s


# ---------------------------------------------------------------------------
# The worked-example oracles (exact Fractions).
# ---------------------------------------------------------------------------
def test_matrix_key_totals() -> None:
    m = _hedge().net_payout_matrix(_point4())
    assert m[4] == Fraction(-10)  # point made -> DP loses 10; places no action
    assert m[6] == Fraction(7)  # place 6 wins 7:6 on 6
    assert m[8] == Fraction(7)  # place 8 wins 7:6 on 8
    assert m[7] == Fraction(-2)  # DP +10, place6 -6, place8 -6 -> -2
    assert m[5] == Fraction(0)  # nothing acts on a 5


def test_single_roll_ev() -> None:
    assert _hedge().single_roll_ev(_point4()) == Fraction(28, 36)


def test_house_drag() -> None:
    assert _hedge().house_drag() == Fraction(7, 22)


# ---------------------------------------------------------------------------
# Matrix structure & state purity.
# ---------------------------------------------------------------------------
def test_matrix_has_all_eleven_totals() -> None:
    m = _hedge().net_payout_matrix(_point4())
    assert set(m) == set(range(2, 13))


def test_matrix_other_totals_zero() -> None:
    m = _hedge().net_payout_matrix(_point4())
    for total in (2, 3, 9, 10, 11, 12):
        assert m[total] == Fraction(0)


def test_net_payout_matrix_does_not_mutate_state() -> None:
    state = _point4()
    _hedge().net_payout_matrix(state)
    # State must be untouched: still POINT, still point 4.
    assert state.phase is Phase.POINT
    assert state.point == 4


# ---------------------------------------------------------------------------
# Empty portfolio: everything degenerates to zero, gracefully.
# ---------------------------------------------------------------------------
def test_empty_matrix_all_zero() -> None:
    m = PortfolioAnalyzer([]).net_payout_matrix(GameState())
    assert set(m) == set(range(2, 13))
    assert all(v == Fraction(0) for v in m.values())


def test_empty_single_roll_ev_zero() -> None:
    assert PortfolioAnalyzer([]).single_roll_ev(GameState()) == Fraction(0)


def test_empty_house_drag_zero() -> None:
    assert PortfolioAnalyzer([]).house_drag() == Fraction(0)


# ---------------------------------------------------------------------------
# house_drag per-type dispatch.
# ---------------------------------------------------------------------------
def test_pass_line_only_house_drag() -> None:
    analyzer = PortfolioAnalyzer([PassLine("pl", Fraction(10))])
    assert analyzer.house_drag() == Fraction(10) * Fraction(7, 495)


def test_odds_bet_contributes_zero_drag() -> None:
    # An odds bet has zero house edge, so it adds nothing to the drag.
    analyzer = PortfolioAnalyzer([PassLine("pl", Fraction(10)), TakeOdds("odds", 4, Fraction(20))])
    assert analyzer.house_drag() == Fraction(10) * Fraction(7, 495)


def test_house_drag_unknown_type_raises() -> None:
    class _MysteryBet(Bet):
        """A Bet subtype the analyzer does not recognize."""

        def resolve(self, roll: DiceRoll, state: GameState) -> Resolution:  # noqa: ARG002
            return Resolution(
                bet_id=self.id,
                status=ResolutionStatus.NO_ACTION,
                delta=Fraction(0),
            )

    analyzer = PortfolioAnalyzer([_MysteryBet("x", Fraction(5))])
    with pytest.raises(TypeError, match="_MysteryBet"):
        analyzer.house_drag()


# ---------------------------------------------------------------------------
# report(): serializable bundle shape.
# ---------------------------------------------------------------------------
def test_report_shape() -> None:
    report = _hedge().report(_point4())
    assert set(report) == {"matrix", "single_roll_ev", "house_drag", "bets"}

    # Matrix: every total present, each value a serialized Fraction payload.
    assert set(report["matrix"]) == set(range(2, 13))
    payload_6 = report["matrix"][6]
    assert set(payload_6) == {"exact", "float", "display"}
    assert payload_6["exact"] == "7/1"

    # Scalars are serialized FractionPayloads (money, not percent).
    for key in ("single_roll_ev", "house_drag"):
        payload = report[key]
        assert set(payload) == {"exact", "float", "display"}

    assert report["single_roll_ev"]["exact"] == "7/9"  # 28/36 reduced
    assert report["house_drag"]["exact"] == "7/22"

    # Per-bet to_dict() round-trips: three bets, each a dict with an id.
    assert len(report["bets"]) == 3
    assert {b["id"] for b in report["bets"]} == {"dp", "p6", "p8"}


def test_report_is_money_not_percent() -> None:
    # as_percent=False -> a 4-dp plain decimal display, never a percentage.
    report = _hedge().report(_point4())
    assert "%" not in report["single_roll_ev"]["display"]
    assert "%" not in report["matrix"][6]["display"]
