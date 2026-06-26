"""Tests for the come-out/point table-level game state machine."""

import pytest

from craps_engine.state import GameState, Phase, PhaseTransition


def test_starts_on_come_out() -> None:
    s = GameState()
    assert s.phase is Phase.COME_OUT
    assert s.point is None


def test_come_out_establishes_point() -> None:
    s = GameState()
    t = s.apply(5)
    assert s.phase is Phase.POINT
    assert s.point == 5
    assert t.point_established
    assert not t.point_made
    assert not t.seven_out
    assert t.previous is Phase.COME_OUT
    assert t.current is Phase.POINT
    assert t.point == 5


def test_come_out_neutral_rolls_do_not_change_phase() -> None:
    s = GameState()
    for total in (2, 3, 7, 11, 12):
        t = s.apply(total)
        assert s.phase is Phase.COME_OUT
        assert s.point is None
        assert not t.point_established
        assert not t.point_made
        assert not t.seven_out
        assert t.previous is Phase.COME_OUT
        assert t.current is Phase.COME_OUT
        assert t.point is None


def test_point_made_returns_to_come_out() -> None:
    s = GameState()
    s.apply(5)
    t = s.apply(5)
    assert s.phase is Phase.COME_OUT
    assert s.point is None
    assert t.point_made
    assert not t.point_established
    assert not t.seven_out
    assert t.previous is Phase.POINT
    assert t.current is Phase.COME_OUT
    assert t.point is None


def test_seven_out() -> None:
    s = GameState()
    s.apply(6)
    t = s.apply(7)
    assert s.phase is Phase.COME_OUT
    assert s.point is None
    assert t.seven_out
    assert not t.point_established
    assert not t.point_made
    assert t.previous is Phase.POINT
    assert t.current is Phase.COME_OUT
    assert t.point is None


def test_point_phase_other_numbers_stay() -> None:
    s = GameState()
    s.apply(8)
    t = s.apply(5)
    assert s.phase is Phase.POINT
    assert s.point == 8
    assert not t.point_established
    assert not t.point_made
    assert not t.seven_out
    assert t.previous is Phase.POINT
    assert t.current is Phase.POINT
    assert t.point == 8


def test_all_point_numbers_establish() -> None:
    for total in (4, 5, 6, 8, 9, 10):
        s = GameState()
        t = s.apply(total)
        assert s.phase is Phase.POINT
        assert s.point == total
        assert t.point_established


def test_apply_rejects_invalid_total() -> None:
    with pytest.raises(ValueError, match="13"):
        GameState().apply(13)
    with pytest.raises(ValueError, match="1"):
        GameState().apply(1)


def test_reset_returns_to_come_out() -> None:
    s = GameState()
    s.apply(8)
    s.reset()
    assert s.phase is Phase.COME_OUT
    assert s.point is None


def test_gamestate_to_dict() -> None:
    s = GameState()
    assert s.to_dict() == {"phase": "come_out", "point": None}
    s.apply(6)
    assert s.to_dict() == {"phase": "point", "point": 6}


def test_phase_transition_to_dict() -> None:
    s = GameState()
    t = s.apply(4)
    assert t.to_dict() == {
        "previous": "come_out",
        "current": "point",
        "point": 4,
        "point_established": True,
        "point_made": False,
        "seven_out": False,
    }


def test_phase_transition_is_dataclass() -> None:
    t = PhaseTransition(
        previous=Phase.POINT,
        current=Phase.COME_OUT,
        point=None,
        point_established=False,
        point_made=False,
        seven_out=True,
    )
    assert t.seven_out
    assert t.to_dict()["seven_out"] is True
