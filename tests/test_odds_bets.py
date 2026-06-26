"""Tests for the Free Odds bets: :class:`TakeOdds` and :class:`LayOdds`.

Written TDD-first. Free Odds pay TRUE odds (zero house edge) and are only live
during the POINT phase (they are "off" on the come-out). These assert the exact
status + signed delta every branch must produce, using exact
:class:`~fractions.Fraction` money against the worked numbers in the task spec:

* TakeOdds(4, 5): point 4 -> +10 (2:1); seven-out -> -5.
* TakeOdds(6, 5): point 6 -> +6 (6:5).
* LayOdds(4, 10): seven -> +5 (inverse 1:2); point made -> -10.
"""

from fractions import Fraction

import pytest

from craps_engine.bets.base import ResolutionStatus
from craps_engine.bets.odds import LayOdds, TakeOdds
from craps_engine.dice import DiceRoll
from craps_engine.state import GameState


def _state_point(p: int) -> GameState:
    """Build a GameState already on POINT with point ``p``."""
    s = GameState()
    s.apply(p)
    return s


# ---------------------------------------------------------------------------
# TakeOdds (Pass side: wins when the point is made before a 7).
# ---------------------------------------------------------------------------
def test_take_odds_win_point_4_pays_true_2to1() -> None:
    r = TakeOdds("t", 4, Fraction(5)).resolve(DiceRoll(2, 2), _state_point(4))  # 4
    assert r.status is ResolutionStatus.WIN
    assert r.delta == Fraction(10)  # 5 * (2/1)
    assert r.note


def test_take_odds_win_point_6_pays_true_6to5() -> None:
    r = TakeOdds("t", 6, Fraction(5)).resolve(DiceRoll(3, 3), _state_point(6))  # 6
    assert r.status is ResolutionStatus.WIN
    assert r.delta == Fraction(6)  # 5 * (6/5)


def test_take_odds_win_point_5_pays_true_3to2() -> None:
    # Exact non-integer Fraction payout: 5 * (3/2) = 15/2. Asserting the exact
    # Fraction (not a float) guards this project's core exact-math guarantee.
    r = TakeOdds("t", 5, Fraction(5)).resolve(DiceRoll(2, 3), _state_point(5))  # 5
    assert r.status is ResolutionStatus.WIN
    assert r.delta == Fraction(15, 2)


def test_take_odds_seven_out_loses() -> None:
    r = TakeOdds("t", 4, Fraction(5)).resolve(DiceRoll(3, 4), _state_point(4))  # 7
    assert r.status is ResolutionStatus.LOSE
    assert r.delta == Fraction(-5)
    assert r.note


def test_take_odds_come_out_no_action() -> None:
    # Odds are NOT working on the come-out (phase is COME_OUT).
    r = TakeOdds("t", 4, Fraction(5)).resolve(DiceRoll(2, 2), GameState())  # 4 on come-out
    assert r.status is ResolutionStatus.NO_ACTION
    assert r.delta == Fraction(0)


def test_take_odds_non_resolving_no_action() -> None:
    r = TakeOdds("t", 4, Fraction(5)).resolve(DiceRoll(2, 3), _state_point(4))  # 5
    assert r.status is ResolutionStatus.NO_ACTION
    assert r.delta == Fraction(0)


# ---------------------------------------------------------------------------
# LayOdds (Don't side: wins when a 7 comes before the point).
# ---------------------------------------------------------------------------
def test_lay_odds_win_seven_pays_inverse_1to2() -> None:
    r = LayOdds("l", 4, Fraction(10)).resolve(DiceRoll(3, 4), _state_point(4))  # 7
    assert r.status is ResolutionStatus.WIN
    assert r.delta == Fraction(5)  # 10 * (1/2)
    assert r.note


def test_lay_odds_point_made_loses() -> None:
    r = LayOdds("l", 4, Fraction(10)).resolve(DiceRoll(2, 2), _state_point(4))  # 4
    assert r.status is ResolutionStatus.LOSE
    assert r.delta == Fraction(-10)
    assert r.note


def test_lay_odds_come_out_no_action() -> None:
    r = LayOdds("l", 4, Fraction(10)).resolve(DiceRoll(3, 4), GameState())  # 7 on come-out
    assert r.status is ResolutionStatus.NO_ACTION
    assert r.delta == Fraction(0)


def test_lay_odds_non_resolving_no_action() -> None:
    r = LayOdds("l", 4, Fraction(10)).resolve(DiceRoll(2, 3), _state_point(4))  # 5
    assert r.status is ResolutionStatus.NO_ACTION
    assert r.delta == Fraction(0)


# ---------------------------------------------------------------------------
# Construction validation + serialization.
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("bad", [7, 11, 2, 3, 12, 1, 13])
def test_invalid_number_raises(bad: int) -> None:
    with pytest.raises(ValueError, match="point"):
        TakeOdds("t", bad, Fraction(5))
    with pytest.raises(ValueError, match="point"):
        LayOdds("l", bad, Fraction(5))


def test_valid_numbers_construct() -> None:
    for n in (4, 5, 6, 8, 9, 10):
        assert TakeOdds("t", n, Fraction(5)).number == n
        assert LayOdds("l", n, Fraction(5)).number == n


def test_to_dict_includes_number() -> None:
    d = TakeOdds("t", 6, Fraction(5)).to_dict()
    assert d["number"] == 6
    # Base keys still present.
    assert d["id"] == "t"
    assert d["type"] == "TakeOdds"
    dl = LayOdds("l", 8, Fraction(5)).to_dict()
    assert dl["number"] == 8
    assert dl["type"] == "LayOdds"


def test_bet_id_mirrors_id() -> None:
    r = TakeOdds("myodds", 4, Fraction(5)).resolve(DiceRoll(2, 2), _state_point(4))
    assert r.bet_id == "myodds"
