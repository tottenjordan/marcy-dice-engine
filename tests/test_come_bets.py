"""Tests for the Come bet's traveling-state resolution.

Written TDD-first: these assert the exact status + signed delta every branch of
:meth:`ComeBet.resolve` must produce. A Come bet rides its OWN come-point and is
oblivious to the table phase, so the tests deliberately exercise BOTH a come-out
:class:`~craps_engine.state.GameState` and one already on a point and assert the
deltas are identical. Deltas use exact :class:`~fractions.Fraction` money (the
Come bet pays 1:1, so net winnings equal the stake).
"""

from fractions import Fraction

import pytest

from craps_engine.bets.base import ResolutionStatus
from craps_engine.bets.come import ComeBet
from craps_engine.dice import DiceRoll
from craps_engine.state import GameState


def _state_point(p: int) -> GameState:
    """Build a GameState already on POINT with point ``p``."""
    s = GameState()
    s.apply(p)
    return s


# ---------------------------------------------------------------------------
# Coming state (come_point is None): behaves like a Pass Line come-out.
# ---------------------------------------------------------------------------
def test_come_coming_wins_on_natural() -> None:
    s = GameState()
    s.apply(4)  # table on a point; come bet is "coming"
    r = ComeBet("c", Fraction(10)).resolve(DiceRoll(5, 6), s)  # 11
    assert r.status is ResolutionStatus.WIN
    assert r.delta == Fraction(10)


def test_come_coming_wins_on_seven() -> None:
    s = GameState()
    s.apply(4)
    r = ComeBet("c", Fraction(10)).resolve(DiceRoll(6, 1), s)  # 7
    assert r.status is ResolutionStatus.WIN
    assert r.delta == Fraction(10)


def test_come_coming_loses_on_craps() -> None:
    s = GameState()
    s.apply(4)
    assert ComeBet("c", Fraction(10)).resolve(DiceRoll(1, 1), s).delta == Fraction(-10)  # 2


def test_come_coming_loses_on_each_craps_number() -> None:
    s = GameState()
    s.apply(4)
    for d in (DiceRoll(1, 1), DiceRoll(1, 2), DiceRoll(6, 6)):  # 2, 3, 12
        r = ComeBet("c", Fraction(10)).resolve(d, s)
        assert r.status is ResolutionStatus.LOSE
        assert r.delta == Fraction(-10)


def test_come_coming_point_number_is_no_action() -> None:
    s = GameState()
    s.apply(4)
    r = ComeBet("c", Fraction(10)).resolve(DiceRoll(3, 3), s)  # 6 -> would establish
    assert r.status is ResolutionStatus.NO_ACTION
    assert r.delta == Fraction(0)
    assert r.note == "come point established"


def test_come_coming_does_not_mutate_come_point() -> None:
    bet = ComeBet("c", Fraction(10))
    bet.resolve(DiceRoll(3, 3), GameState())  # 6 would establish a come-point
    assert bet.come_point is None  # resolve is PURE: no mutation


# ---------------------------------------------------------------------------
# Established state (come_point set): races the come-point against the 7.
# ---------------------------------------------------------------------------
def test_come_established_wins_when_point_made() -> None:
    bet = ComeBet("c", Fraction(10), come_point=6)
    r = bet.resolve(DiceRoll(3, 3), GameState())  # 6
    assert r.status is ResolutionStatus.WIN
    assert r.delta == Fraction(10)
    assert r.note == "come point made"


def test_come_established_loses_on_seven_out() -> None:
    bet = ComeBet("c", Fraction(10), come_point=6)
    r = bet.resolve(DiceRoll(3, 4), GameState())  # 7
    assert r.status is ResolutionStatus.LOSE
    assert r.delta == Fraction(-10)
    assert r.note == "seven out"


def test_come_established_middle_total_is_no_action() -> None:
    bet = ComeBet("c", Fraction(10), come_point=6)
    r = bet.resolve(DiceRoll(2, 3), GameState())  # 5: neither the point nor a 7
    assert r.status is ResolutionStatus.NO_ACTION
    assert r.delta == Fraction(0)


def test_come_established_does_not_mutate_come_point() -> None:
    bet = ComeBet("c", Fraction(10), come_point=6)
    bet.resolve(DiceRoll(3, 4), GameState())  # seven out
    assert bet.come_point == 6  # resolve is PURE: no mutation


# ---------------------------------------------------------------------------
# Phase-independence: a Come bet ignores the table phase entirely.
# ---------------------------------------------------------------------------
def test_come_resolves_identically_regardless_of_phase() -> None:
    come_out = GameState()  # COME_OUT, no point
    on_point = _state_point(8)  # POINT, point 8
    for total_dice in (DiceRoll(5, 6), DiceRoll(1, 1), DiceRoll(3, 3)):
        a = ComeBet("c", Fraction(10)).resolve(total_dice, come_out)
        b = ComeBet("c", Fraction(10)).resolve(total_dice, on_point)
        assert a.status is b.status
        assert a.delta == b.delta


# ---------------------------------------------------------------------------
# Construction validation (fail-fast).
# ---------------------------------------------------------------------------
def test_come_rejects_invalid_come_point() -> None:
    with pytest.raises(ValueError, match="7"):
        ComeBet("c", 10, come_point=7)


def test_come_accepts_int_amount_and_none_come_point() -> None:
    bet = ComeBet("c", 10)  # int amount, default come_point None
    assert bet.amount == Fraction(10)
    assert bet.come_point is None
    assert bet.working is True


def test_come_accepts_each_valid_come_point() -> None:
    for p in (4, 5, 6, 8, 9, 10):
        assert ComeBet("c", 10, come_point=p).come_point == p
