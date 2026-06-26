"""Tests for :class:`~craps_engine.bets.place.PlaceBet`.

Written TDD-first. Place bets win at PLACE odds when their number rolls and lose
when a 7 rolls. By craps convention they are OFF (not working) on the come-out
roll by default, but the player may turn them ON. These assert the exact
status + signed delta every branch must produce, using exact
:class:`~fractions.Fraction` money against the worked numbers in the task spec:

* Place 6 amount 6 (POINT): 6 -> +7 (7:6); 7 -> -6; 5 -> no action.
* Place 5 amount 5 (POINT): 5 -> +7 (7:5).
* Place 4 amount 5 (POINT): 4 -> +9 (9:5).
* Place 6 amount 6 on COME_OUT default (off) -> no action.
* Place 6 amount 6 on COME_OUT, working=True -> +7 (player turned it on).
"""

from fractions import Fraction

import pytest

from craps_engine.bets.base import ResolutionStatus
from craps_engine.bets.place import PlaceBet
from craps_engine.dice import DiceRoll
from craps_engine.state import GameState


def _state_point(p: int) -> GameState:
    """Build a GameState already on POINT with point ``p``."""
    s = GameState()
    s.apply(p)
    return s


# ---------------------------------------------------------------------------
# Worked numbers in the POINT phase (the default working window for place bets).
# ---------------------------------------------------------------------------
def test_place_6_hit_pays_7to6() -> None:
    r = PlaceBet("p", 6, Fraction(6)).resolve(DiceRoll(3, 3), _state_point(4))  # 6
    assert r.status is ResolutionStatus.WIN
    assert r.delta == Fraction(7)  # 6 * (7/6)
    assert r.note


def test_place_5_hit_pays_7to5() -> None:
    r = PlaceBet("p", 5, Fraction(5)).resolve(DiceRoll(2, 3), _state_point(4))  # 5
    assert r.status is ResolutionStatus.WIN
    assert r.delta == Fraction(7)  # 5 * (7/5)


def test_place_4_hit_pays_9to5() -> None:
    r = PlaceBet("p", 4, Fraction(5)).resolve(DiceRoll(2, 2), _state_point(6))  # 4
    assert r.status is ResolutionStatus.WIN
    assert r.delta == Fraction(9)  # 5 * (9/5)


def test_place_seven_out_loses() -> None:
    r = PlaceBet("p", 6, Fraction(6)).resolve(DiceRoll(3, 4), _state_point(6))  # 7
    assert r.status is ResolutionStatus.LOSE
    assert r.delta == Fraction(-6)
    assert r.note


def test_place_non_resolving_no_action() -> None:
    # On POINT, a total that is neither the number nor a 7 leaves it standing.
    r = PlaceBet("p", 6, Fraction(6)).resolve(DiceRoll(2, 3), _state_point(4))  # 5
    assert r.status is ResolutionStatus.NO_ACTION
    assert r.delta == Fraction(0)


# ---------------------------------------------------------------------------
# Come-out OFF-by-default convention, and the working=True override.
# ---------------------------------------------------------------------------
def test_place_off_on_come_out_by_default() -> None:
    # Default working=False: the place bet is OFF on the come-out, so even its
    # own number produces NO_ACTION.
    bet = PlaceBet("p", 6, Fraction(6))
    assert bet.working is False
    r = bet.resolve(DiceRoll(3, 3), GameState())  # 6 on come-out
    assert r.status is ResolutionStatus.NO_ACTION
    assert r.delta == Fraction(0)


def test_place_off_on_come_out_does_not_lose_on_seven() -> None:
    # An off place bet is not at risk on a come-out 7 either.
    r = PlaceBet("p", 6, Fraction(6)).resolve(DiceRoll(3, 4), GameState())  # 7 on come-out
    assert r.status is ResolutionStatus.NO_ACTION
    assert r.delta == Fraction(0)


def test_place_working_true_on_come_out_wins() -> None:
    # Player turned the bet ON for the come-out: it now wins on its number.
    r = PlaceBet("p", 6, Fraction(6), working=True).resolve(
        DiceRoll(3, 3),
        GameState(),
    )  # 6 on come-out
    assert r.status is ResolutionStatus.WIN
    assert r.delta == Fraction(7)


def test_place_working_true_on_come_out_loses_on_seven() -> None:
    # When turned on, it is also at risk on a come-out 7.
    r = PlaceBet("p", 6, Fraction(6), working=True).resolve(
        DiceRoll(3, 4),
        GameState(),
    )  # 7 on come-out
    assert r.status is ResolutionStatus.LOSE
    assert r.delta == Fraction(-6)


def test_place_working_in_point_phase_always_live() -> None:
    # During POINT the bet is live regardless of the working flag's default.
    bet = PlaceBet("p", 8, Fraction(6))  # default working=False
    r = bet.resolve(DiceRoll(4, 4), _state_point(4))  # 8
    assert r.status is ResolutionStatus.WIN
    assert r.delta == Fraction(7)  # 6 * (7/6)


# ---------------------------------------------------------------------------
# All six place numbers' payouts, including an exact-fraction case (35/6).
# ---------------------------------------------------------------------------
@pytest.mark.parametrize(
    ("number", "amount", "expected"),
    [
        (4, Fraction(5), Fraction(9)),  # 5 * 9/5
        (10, Fraction(5), Fraction(9)),  # 5 * 9/5
        (5, Fraction(5), Fraction(7)),  # 5 * 7/5
        (9, Fraction(5), Fraction(7)),  # 5 * 7/5
        (6, Fraction(5), Fraction(35, 6)),  # 5 * 7/6 -> exact fraction
        (8, Fraction(5), Fraction(35, 6)),  # 5 * 7/6 -> exact fraction
    ],
)
def test_all_place_numbers_payouts(number: int, amount: Fraction, expected: Fraction) -> None:
    # Roll the number itself (two equal dice work for 4/6/8/10; 5/9 need a split).
    roll = DiceRoll(2, 3) if number == 5 else DiceRoll(4, 5) if number == 9 else None
    if roll is None:
        roll = DiceRoll(number // 2, number - number // 2)
    # Use a point different from the placed number so the state stays on POINT.
    point = 4 if number != 4 else 5
    r = PlaceBet("p", number, amount).resolve(roll, _state_point(point))
    assert r.status is ResolutionStatus.WIN
    assert r.delta == expected


# ---------------------------------------------------------------------------
# Construction validation + serialization.
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("bad", [7, 11, 2, 3, 12, 1, 13])
def test_invalid_number_raises(bad: int) -> None:
    with pytest.raises(ValueError, match="place"):
        PlaceBet("p", bad, Fraction(5))


def test_valid_numbers_construct() -> None:
    for n in (4, 5, 6, 8, 9, 10):
        assert PlaceBet("p", n, Fraction(5)).number == n


def test_amount_accepts_int() -> None:
    assert PlaceBet("p", 6, 6).amount == Fraction(6)


def test_to_dict_includes_number() -> None:
    d = PlaceBet("p", 6, Fraction(6)).to_dict()
    assert d["number"] == 6
    assert d["id"] == "p"
    assert d["type"] == "PlaceBet"
    assert d["working"] is False


def test_bet_id_mirrors_id() -> None:
    r = PlaceBet("mybet", 6, Fraction(6)).resolve(DiceRoll(3, 3), _state_point(4))
    assert r.bet_id == "mybet"
