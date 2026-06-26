"""Tests for the bet lifecycle hooks: ``remains_on_table`` and ``advance``.

These cover the two overridable hooks on the :class:`~craps_engine.bets.base.Bet`
ABC plus the subclass overrides: the default keep-on-table rule, the standing
:class:`~craps_engine.bets.place.PlaceBet` override, the no-op default
:meth:`Bet.advance`, and the come-family ``advance`` that establishes the
come-point.
"""

from __future__ import annotations

from fractions import Fraction

import pytest

from craps_engine.bets.base import Resolution, ResolutionStatus
from craps_engine.bets.come import ComeBet, DontCome
from craps_engine.bets.line import PassLine
from craps_engine.bets.place import PlaceBet
from craps_engine.dice import DiceRoll


def _resolution(status: ResolutionStatus) -> Resolution:
    """Build a minimal :class:`Resolution` carrying just the given status."""
    return Resolution(bet_id="b", status=status, delta=Fraction(0))


# A point-number roll (total 6) and a non-point roll (total 7), reused below.
_POINT_ROLL = DiceRoll(3, 3)  # total 6
_SEVEN_ROLL = DiceRoll(3, 4)  # total 7
_ELEVEN_ROLL = DiceRoll(5, 6)  # total 11


class TestDefaultRemainsOnTable:
    """The base :meth:`Bet.remains_on_table` keeps only unresolved/pushed bets."""

    @pytest.mark.parametrize(
        ("status", "expected"),
        [
            (ResolutionStatus.NO_ACTION, True),
            (ResolutionStatus.PUSH, True),
            (ResolutionStatus.WIN, False),
            (ResolutionStatus.LOSE, False),
        ],
    )
    def test_default_keep_rule(self, status: ResolutionStatus, *, expected: bool) -> None:
        """NO_ACTION/PUSH stay; WIN/LOSE come down (default rule)."""
        bet = PassLine("pl", 10)
        assert bet.remains_on_table(_resolution(status), _SEVEN_ROLL) is expected


class TestPlaceRemainsOnTable:
    """A place bet is a STANDING wager: a win keeps it up on the felt."""

    @pytest.mark.parametrize(
        ("status", "expected"),
        [
            (ResolutionStatus.WIN, True),
            (ResolutionStatus.NO_ACTION, True),
            (ResolutionStatus.PUSH, True),
            (ResolutionStatus.LOSE, False),
        ],
    )
    def test_standing_keeps_on_win(self, status: ResolutionStatus, *, expected: bool) -> None:
        """Place bets stay up on WIN/NO_ACTION/PUSH and only come down on LOSE."""
        bet = PlaceBet("p6", 6, 12)
        assert bet.remains_on_table(_resolution(status), _POINT_ROLL) is expected


class TestDefaultAdvance:
    """The base :meth:`Bet.advance` is a no-op returning ``None``."""

    def test_passline_advance_is_noop(self) -> None:
        """A PassLine has no per-roll transition: advance returns None, no raise."""
        bet = PassLine("pl", 10)
        result = bet.advance(_POINT_ROLL, _resolution(ResolutionStatus.NO_ACTION))
        assert result is None

    def test_place_advance_is_noop_and_does_not_mutate(self) -> None:
        """A PlaceBet's advance is a no-op and leaves its fields unchanged."""
        bet = PlaceBet("p6", 6, 12)
        before = (bet.number, bet.amount, bet.working)
        result = bet.advance(_POINT_ROLL, _resolution(ResolutionStatus.WIN))
        assert result is None
        assert (bet.number, bet.amount, bet.working) == before


class TestComeBetAdvance:
    """``ComeBet.advance`` establishes the come-point on a point-number roll."""

    def test_point_number_establishes_come_point(self) -> None:
        """A traveling come bet binds its come-point to a point total (6)."""
        bet = ComeBet("c", 10)
        assert bet.come_point is None
        bet.advance(_POINT_ROLL, _resolution(ResolutionStatus.NO_ACTION))
        assert bet.come_point == 6

    @pytest.mark.parametrize("roll", [_SEVEN_ROLL, _ELEVEN_ROLL])
    def test_non_point_leaves_come_point_none(self, roll: DiceRoll) -> None:
        """A 7 or 11 does not establish a come-point (stays None)."""
        bet = ComeBet("c", 10)
        bet.advance(roll, _resolution(ResolutionStatus.WIN))
        assert bet.come_point is None

    def test_established_come_point_unchanged(self) -> None:
        """An already-established come bet keeps its existing come-point."""
        bet = ComeBet("c", 10, come_point=5)
        bet.advance(_POINT_ROLL, _resolution(ResolutionStatus.NO_ACTION))
        assert bet.come_point == 5


class TestDontComeAdvance:
    """``DontCome.advance`` establishes the come-point identically."""

    def test_point_number_establishes_come_point(self) -> None:
        """A traveling don't-come bet binds its come-point to a point total (6)."""
        bet = DontCome("dc", 10)
        assert bet.come_point is None
        bet.advance(_POINT_ROLL, _resolution(ResolutionStatus.NO_ACTION))
        assert bet.come_point == 6

    def test_non_point_leaves_come_point_none(self) -> None:
        """A 7 does not establish a come-point (stays None)."""
        bet = DontCome("dc", 10)
        bet.advance(_SEVEN_ROLL, _resolution(ResolutionStatus.WIN))
        assert bet.come_point is None

    def test_established_come_point_unchanged(self) -> None:
        """An already-established don't-come bet keeps its existing come-point."""
        bet = DontCome("dc", 10, come_point=9)
        bet.advance(_POINT_ROLL, _resolution(ResolutionStatus.NO_ACTION))
        assert bet.come_point == 9
