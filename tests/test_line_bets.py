"""Tests for the Pass Line and Don't Pass line bets.

Written TDD-first: these assert the exact status + signed delta every branch
of :meth:`PassLine.resolve` / :meth:`DontPass.resolve` must produce, against
both the come-out and point phases. Deltas use exact :class:`~fractions.Fraction`
money (1:1 payout -> net winnings equal the stake).
"""

from fractions import Fraction

from craps_engine.bets.base import ResolutionStatus
from craps_engine.bets.line import DontPass, PassLine
from craps_engine.dice import DiceRoll
from craps_engine.state import GameState


def _state_point(p: int) -> GameState:
    """Build a GameState already on POINT with point ``p``."""
    s = GameState()
    s.apply(p)
    return s


# ---------------------------------------------------------------------------
# Pass Line
# ---------------------------------------------------------------------------
def test_pass_comeout_naturals_win() -> None:
    s = GameState()
    assert PassLine("p", Fraction(10)).resolve(DiceRoll(5, 6), s).delta == Fraction(10)  # 11
    assert PassLine("p", Fraction(10)).resolve(DiceRoll(6, 1), s).delta == Fraction(10)  # 7


def test_pass_comeout_craps_lose() -> None:
    s = GameState()
    for d in (DiceRoll(1, 1), DiceRoll(1, 2), DiceRoll(6, 6)):  # 2,3,12
        assert PassLine("p", Fraction(10)).resolve(d, s).delta == Fraction(-10)


def test_pass_comeout_point_no_action() -> None:
    s = GameState()
    r = PassLine("p", Fraction(10)).resolve(DiceRoll(2, 2), s)  # 4
    assert r.status is ResolutionStatus.NO_ACTION
    assert r.delta == Fraction(0)


def test_pass_point_made_and_seven_out() -> None:
    assert PassLine("p", Fraction(10)).resolve(DiceRoll(2, 2), _state_point(4)).delta == Fraction(
        10
    )
    assert PassLine("p", Fraction(10)).resolve(DiceRoll(3, 4), _state_point(4)).delta == Fraction(
        -10
    )


def test_pass_point_non_resolving_no_action() -> None:
    s = _state_point(4)
    r = PassLine("p", Fraction(10)).resolve(DiceRoll(2, 3), s)  # 5, not the point, not a 7
    assert r.status is ResolutionStatus.NO_ACTION
    assert r.delta == Fraction(0)


def test_pass_status_and_notes() -> None:
    s = GameState()
    win = PassLine("p", Fraction(10)).resolve(DiceRoll(5, 6), s)  # 11
    assert win.status is ResolutionStatus.WIN
    assert win.note
    lose = PassLine("p", Fraction(10)).resolve(DiceRoll(1, 1), s)  # 2
    assert lose.status is ResolutionStatus.LOSE
    assert lose.note
    made = PassLine("p", Fraction(10)).resolve(DiceRoll(2, 2), _state_point(4))
    assert made.status is ResolutionStatus.WIN
    assert made.note
    out = PassLine("p", Fraction(10)).resolve(DiceRoll(3, 4), _state_point(4))
    assert out.status is ResolutionStatus.LOSE
    assert out.note


def test_pass_bet_id_mirrors_id() -> None:
    r = PassLine("mypass", Fraction(10)).resolve(DiceRoll(5, 6), GameState())
    assert r.bet_id == "mypass"


# ---------------------------------------------------------------------------
# Don't Pass
# ---------------------------------------------------------------------------
def test_dont_pass_comeout() -> None:
    s = GameState()
    assert DontPass("d", Fraction(10)).resolve(DiceRoll(1, 1), s).delta == Fraction(10)  # 2 win
    assert DontPass("d", Fraction(10)).resolve(DiceRoll(5, 6), s).delta == Fraction(-10)  # 11 lose
    r12 = DontPass("d", Fraction(10)).resolve(DiceRoll(6, 6), s)  # 12 push
    assert r12.status is ResolutionStatus.PUSH
    assert r12.delta == Fraction(0)


def test_dont_pass_comeout_three_wins() -> None:
    r = DontPass("d", Fraction(10)).resolve(DiceRoll(1, 2), GameState())  # 3 win
    assert r.status is ResolutionStatus.WIN
    assert r.delta == Fraction(10)


def test_dont_pass_comeout_seven_lose() -> None:
    r = DontPass("d", Fraction(10)).resolve(DiceRoll(3, 4), GameState())  # 7 lose
    assert r.status is ResolutionStatus.LOSE
    assert r.delta == Fraction(-10)


def test_dont_pass_comeout_point_no_action() -> None:
    r = DontPass("d", Fraction(10)).resolve(DiceRoll(2, 2), GameState())  # 4, point number
    assert r.status is ResolutionStatus.NO_ACTION
    assert r.delta == Fraction(0)


def test_dont_pass_point_phase() -> None:
    assert DontPass("d", Fraction(10)).resolve(DiceRoll(3, 4), _state_point(4)).delta == Fraction(
        10
    )  # 7 win
    assert DontPass("d", Fraction(10)).resolve(DiceRoll(2, 2), _state_point(4)).delta == Fraction(
        -10
    )  # point made lose


def test_dont_pass_point_no_action() -> None:
    s = _state_point(4)
    r = DontPass("d", Fraction(10)).resolve(DiceRoll(2, 3), s)  # 5, not point, not 7
    assert r.status is ResolutionStatus.NO_ACTION
    assert r.delta == Fraction(0)


def test_dont_pass_status_and_notes() -> None:
    seven_out = DontPass("d", Fraction(10)).resolve(DiceRoll(3, 4), _state_point(4))
    assert seven_out.status is ResolutionStatus.WIN
    assert seven_out.note
    made = DontPass("d", Fraction(10)).resolve(DiceRoll(2, 2), _state_point(4))
    assert made.status is ResolutionStatus.LOSE
    assert made.note
    push = DontPass("d", Fraction(10)).resolve(DiceRoll(6, 6), GameState())  # bar 12
    assert push.note


def test_dont_pass_bet_id_mirrors_id() -> None:
    r = DontPass("mydont", Fraction(10)).resolve(DiceRoll(1, 1), GameState())
    assert r.bet_id == "mydont"
