"""Tests for the Free Odds bets: :class:`TakeOdds` and :class:`LayOdds`.

Written TDD-first. Free Odds pay TRUE odds (zero house edge). During the POINT
phase they are live; on the come-out they are OFF BY DEFAULT (real-table
behaviour), meaning a come-point or a 7 there RETURNS the odds to the player (a
PUSH that comes down) rather than winning/losing -- unless the player has called
them ON for the come-out via ``come_out_working``. These assert the exact status
+ signed delta every branch must produce, using exact
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


def test_take_odds_come_out_off_returns_on_come_point() -> None:
    # OFF on the come-out (default): a come-point roll RETURNS the odds (PUSH),
    # and the bet comes down (does not stand orphaned).
    bet = TakeOdds("t", 4, Fraction(5))
    roll = DiceRoll(2, 2)  # 4 on come-out
    r = bet.resolve(roll, GameState())
    assert r.status is ResolutionStatus.PUSH
    assert r.delta == Fraction(0)
    assert bet.remains_on_table(r, roll) is False


def test_take_odds_come_out_off_returns_on_seven() -> None:
    bet = TakeOdds("t", 4, Fraction(5))
    roll = DiceRoll(3, 4)  # 7 on come-out
    r = bet.resolve(roll, GameState())
    assert r.status is ResolutionStatus.PUSH
    assert r.delta == Fraction(0)
    assert bet.remains_on_table(r, roll) is False


def test_take_odds_come_out_off_non_resolving_stands() -> None:
    # OFF on the come-out, a non-resolving total leaves the odds untouched (they
    # stand for the next roll).
    bet = TakeOdds("t", 4, Fraction(5))
    roll = DiceRoll(2, 3)  # 5 on come-out
    r = bet.resolve(roll, GameState())
    assert r.status is ResolutionStatus.NO_ACTION
    assert r.delta == Fraction(0)
    assert bet.remains_on_table(r, roll) is True


def test_take_odds_come_out_working_settles_win() -> None:
    # Called ON for the come-out: settles at true odds like during the point.
    r = TakeOdds("t", 4, Fraction(5), come_out_working=True).resolve(
        DiceRoll(2, 2), GameState()
    )  # 4 on come-out
    assert r.status is ResolutionStatus.WIN
    assert r.delta == Fraction(10)


def test_take_odds_come_out_working_settles_lose() -> None:
    r = TakeOdds("t", 4, Fraction(5), come_out_working=True).resolve(
        DiceRoll(3, 4), GameState()
    )  # 7 on come-out
    assert r.status is ResolutionStatus.LOSE
    assert r.delta == Fraction(-5)


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


def test_lay_odds_come_out_off_returns_on_seven() -> None:
    bet = LayOdds("l", 4, Fraction(10))
    roll = DiceRoll(3, 4)  # 7 on come-out
    r = bet.resolve(roll, GameState())
    assert r.status is ResolutionStatus.PUSH
    assert r.delta == Fraction(0)
    assert bet.remains_on_table(r, roll) is False


def test_lay_odds_come_out_off_returns_on_come_point() -> None:
    bet = LayOdds("l", 4, Fraction(10))
    roll = DiceRoll(2, 2)  # 4 on come-out
    r = bet.resolve(roll, GameState())
    assert r.status is ResolutionStatus.PUSH
    assert r.delta == Fraction(0)
    assert bet.remains_on_table(r, roll) is False


def test_lay_odds_come_out_working_settles_win() -> None:
    r = LayOdds("l", 4, Fraction(10), come_out_working=True).resolve(
        DiceRoll(3, 4), GameState()
    )  # 7 on come-out
    assert r.status is ResolutionStatus.WIN
    assert r.delta == Fraction(5)


def test_lay_odds_come_out_working_settles_lose() -> None:
    r = LayOdds("l", 4, Fraction(10), come_out_working=True).resolve(
        DiceRoll(2, 2), GameState()
    )  # 4 on come-out
    assert r.status is ResolutionStatus.LOSE
    assert r.delta == Fraction(-10)


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


def test_to_dict_includes_come_out_working() -> None:
    # Defaults OFF for the come-out (real-table default); round-trips both ways.
    assert TakeOdds("t", 6, Fraction(5)).to_dict()["come_out_working"] is False
    assert LayOdds("l", 8, Fraction(5), come_out_working=True).to_dict()["come_out_working"] is True


def test_remains_on_table_point_phase_win_and_lose_come_down() -> None:
    # Standard point-phase settlement still takes the odds down on WIN/LOSE and
    # leaves them up on NO_ACTION (a returned come-out PUSH is covered above).
    bet = TakeOdds("t", 4, Fraction(5))
    win = bet.resolve(DiceRoll(2, 2), _state_point(4))  # 4 -> WIN
    assert bet.remains_on_table(win, DiceRoll(2, 2)) is False
    lose = bet.resolve(DiceRoll(3, 4), _state_point(4))  # 7 -> LOSE
    assert bet.remains_on_table(lose, DiceRoll(3, 4)) is False
    stand = bet.resolve(DiceRoll(2, 3), _state_point(4))  # 5 -> NO_ACTION
    assert bet.remains_on_table(stand, DiceRoll(2, 3)) is True


def test_bet_id_mirrors_id() -> None:
    r = TakeOdds("myodds", 4, Fraction(5)).resolve(DiceRoll(2, 2), _state_point(4))
    assert r.bet_id == "myodds"
