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
from craps_engine.bets.come import ComeBet, DontCome
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


# ---------------------------------------------------------------------------
# establish_come_point mutator: the ONLY path that sets come_point.
# ---------------------------------------------------------------------------
def test_establish_come_point_on_fresh_bet_sets_and_returns_true() -> None:
    bet = ComeBet("c", Fraction(10))
    assert bet.establish_come_point(6) is True
    assert bet.come_point == 6


def test_establish_come_point_is_one_shot() -> None:
    bet = ComeBet("c", Fraction(10))
    bet.establish_come_point(6)
    assert bet.establish_come_point(8) is False  # already traveling
    assert bet.come_point == 6  # unchanged


def test_establish_come_point_rejects_seven() -> None:
    bet = ComeBet("c", Fraction(10))
    assert bet.establish_come_point(7) is False
    assert bet.come_point is None


def test_establish_come_point_rejects_craps_number() -> None:
    bet = ComeBet("c", Fraction(10))
    assert bet.establish_come_point(2) is False
    assert bet.come_point is None


def test_establish_come_point_for_every_valid_point() -> None:
    for p in (4, 5, 6, 8, 9, 10):
        bet = ComeBet("c", Fraction(10))
        assert bet.establish_come_point(p) is True
        assert bet.come_point == p


def test_establish_come_point_does_not_break_resolve_purity() -> None:
    # resolve must NOT establish the come-point: only the mutator does.
    bet = ComeBet("c", Fraction(10))
    bet.resolve(DiceRoll(3, 3), GameState())  # 6 would establish
    assert bet.come_point is None


# ---------------------------------------------------------------------------
# to_dict: the come-point round-trips alongside the base bet fields.
# ---------------------------------------------------------------------------
def test_to_dict_traveling_has_none_come_point_and_base_keys() -> None:
    d = ComeBet("c", Fraction(10)).to_dict()
    assert d["come_point"] is None
    assert d["id"] == "c"
    assert d["type"] == "ComeBet"
    assert d["working"] is True
    assert "amount" in d


def test_to_dict_established_round_trips_come_point() -> None:
    d = ComeBet("c", Fraction(10), come_point=6).to_dict()
    assert d["come_point"] == 6
    assert d["type"] == "ComeBet"


# ===========================================================================
# DontCome: the wrong-way come bet, riding its OWN come-point (bar 12). It
# mirrors Don't Pass but keyed on self.come_point, and -- like ComeBet --
# IGNORES the table phase entirely.
# ===========================================================================
# ---------------------------------------------------------------------------
# Coming state (come_point is None): behaves like a Don't Pass come-out.
# ---------------------------------------------------------------------------
def test_dont_come_coming_wins_on_each_craps_number() -> None:
    s = GameState()
    s.apply(4)  # table on a point; don't-come bet is "coming"
    for d in (DiceRoll(1, 1), DiceRoll(1, 2)):  # 2, 3
        r = DontCome("dc", Fraction(10)).resolve(d, s)
        assert r.status is ResolutionStatus.WIN
        assert r.delta == Fraction(10)


def test_dont_come_coming_loses_on_each_natural() -> None:
    s = GameState()
    s.apply(4)
    for d in (DiceRoll(3, 4), DiceRoll(5, 6)):  # 7, 11
        r = DontCome("dc", Fraction(10)).resolve(d, s)
        assert r.status is ResolutionStatus.LOSE
        assert r.delta == Fraction(-10)


def test_dont_come_coming_pushes_on_bar_twelve() -> None:
    s = GameState()
    s.apply(4)
    r = DontCome("dc", Fraction(10)).resolve(DiceRoll(6, 6), s)  # 12
    assert r.status is ResolutionStatus.PUSH
    assert r.delta == Fraction(0)
    assert r.note == "bar 12 push"


def test_dont_come_coming_point_number_is_no_action() -> None:
    s = GameState()
    s.apply(4)
    r = DontCome("dc", Fraction(10)).resolve(DiceRoll(3, 3), s)  # 6 -> would establish
    assert r.status is ResolutionStatus.NO_ACTION
    assert r.delta == Fraction(0)
    assert r.note == "come point established"


# ---------------------------------------------------------------------------
# Established state (come_point set): the seven WINS, the come-point LOSES.
# ---------------------------------------------------------------------------
def test_dont_come_established_wins_on_seven_out() -> None:
    bet = DontCome("dc", Fraction(10), come_point=6)
    r = bet.resolve(DiceRoll(3, 4), GameState())  # 7
    assert r.status is ResolutionStatus.WIN
    assert r.delta == Fraction(10)


def test_dont_come_established_loses_when_point_made() -> None:
    bet = DontCome("dc", Fraction(10), come_point=6)
    r = bet.resolve(DiceRoll(3, 3), GameState())  # 6
    assert r.status is ResolutionStatus.LOSE
    assert r.delta == Fraction(-10)


def test_dont_come_established_middle_total_is_no_action() -> None:
    bet = DontCome("dc", Fraction(10), come_point=6)
    r = bet.resolve(DiceRoll(2, 3), GameState())  # 5: neither the point nor a 7
    assert r.status is ResolutionStatus.NO_ACTION
    assert r.delta == Fraction(0)


# ---------------------------------------------------------------------------
# Phase-independence and purity.
# ---------------------------------------------------------------------------
def test_dont_come_resolves_identically_regardless_of_phase() -> None:
    come_out = GameState()  # COME_OUT, no point
    on_point = _state_point(8)  # POINT, point 8
    for total_dice in (DiceRoll(5, 6), DiceRoll(1, 1), DiceRoll(3, 3)):
        a = DontCome("dc", Fraction(10)).resolve(total_dice, come_out)
        b = DontCome("dc", Fraction(10)).resolve(total_dice, on_point)
        assert a.status is b.status
        assert a.delta == b.delta


def test_dont_come_resolve_is_pure_does_not_establish_come_point() -> None:
    bet = DontCome("dc", Fraction(10))
    bet.resolve(DiceRoll(3, 3), GameState())  # 6 would establish a come-point
    assert bet.come_point is None  # resolve is PURE: no mutation


# ---------------------------------------------------------------------------
# establish_come_point mutator works on DontCome too.
# ---------------------------------------------------------------------------
def test_dont_come_establish_come_point_sets_and_returns_true() -> None:
    bet = DontCome("dc", Fraction(10))
    assert bet.establish_come_point(6) is True
    assert bet.come_point == 6


def test_dont_come_establish_come_point_is_one_shot() -> None:
    bet = DontCome("dc", Fraction(10))
    bet.establish_come_point(6)
    assert bet.establish_come_point(8) is False
    assert bet.come_point == 6


def test_dont_come_establish_come_point_rejects_seven() -> None:
    bet = DontCome("dc", Fraction(10))
    assert bet.establish_come_point(7) is False
    assert bet.come_point is None


# ---------------------------------------------------------------------------
# Construction validation and serialization.
# ---------------------------------------------------------------------------
def test_dont_come_rejects_invalid_come_point() -> None:
    with pytest.raises(ValueError, match="7"):
        DontCome("dc", 10, come_point=7)


def test_dont_come_to_dict_traveling_has_none_come_point() -> None:
    d = DontCome("dc", Fraction(10)).to_dict()
    assert d["come_point"] is None
    assert d["type"] == "DontCome"
    assert d["id"] == "dc"
    assert d["working"] is True
    assert "amount" in d


def test_dont_come_to_dict_established_round_trips_come_point() -> None:
    d = DontCome("dc", Fraction(10), come_point=6).to_dict()
    assert d["come_point"] == 6
    assert d["type"] == "DontCome"
