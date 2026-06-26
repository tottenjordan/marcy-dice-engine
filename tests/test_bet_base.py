"""Tests for the Bet ABC and the Resolution result model."""

from fractions import Fraction

import pytest

from craps_engine.bets.base import Bet, Resolution, ResolutionStatus
from craps_engine.dice import DiceRoll
from craps_engine.state import GameState


class _DummyBet(Bet):
    """Trivial concrete Bet used solely to exercise the ABC machinery.

    Its :meth:`resolve` always reports a WIN whose ``delta`` is ``+amount``,
    honoring the sign convention: a WIN's delta is the (positive) net winnings.
    """

    def resolve(self, roll: DiceRoll, state: GameState) -> Resolution:  # noqa: ARG002
        return Resolution(
            bet_id=self.id,
            status=ResolutionStatus.WIN,
            delta=self.amount,
        )


def test_cannot_instantiate_bet_directly() -> None:
    # Bet is abstract: instantiating it must fail because `resolve` is abstract.
    with pytest.raises(TypeError):
        Bet("x", Fraction(5))  # type: ignore[abstract]


def test_resolution_status_members_exist() -> None:
    assert ResolutionStatus.WIN.value == "win"
    assert ResolutionStatus.LOSE.value == "lose"
    assert ResolutionStatus.PUSH.value == "push"
    assert ResolutionStatus.NO_ACTION.value == "no_action"


def test_push_and_no_action_have_zero_delta() -> None:
    push = Resolution(bet_id="a", status=ResolutionStatus.PUSH, delta=Fraction(0))
    no_action = Resolution(bet_id="a", status=ResolutionStatus.NO_ACTION, delta=Fraction(0))
    assert push.delta == Fraction(0)
    assert no_action.delta == Fraction(0)


def test_resolution_to_dict_shape_and_serialized_delta() -> None:
    res = Resolution(
        bet_id="pass-1",
        status=ResolutionStatus.LOSE,
        delta=Fraction(-10),
        note="craps out",
    )
    payload = res.to_dict()
    assert payload["bet_id"] == "pass-1"
    assert payload["status"] == "lose"
    assert payload["note"] == "craps out"
    # Money is serialized as a non-percent Fraction payload.
    assert payload["delta"]["exact"] == "-10/1"
    assert payload["delta"]["float"] == -10.0
    assert payload["delta"]["display"] == "-10.0000"


def test_winning_resolution_delta_is_positive_net() -> None:
    # The dummy WIN reports +amount, the documented WIN sign convention.
    bet = _DummyBet("w", Fraction(5))
    res = bet.resolve(DiceRoll(3, 4), GameState())
    assert res.status is ResolutionStatus.WIN
    assert res.delta == Fraction(5)
    assert res.delta > 0


def test_bet_to_dict_shape() -> None:
    bet = _DummyBet("x", Fraction(5))
    payload = bet.to_dict()
    assert payload["id"] == "x"
    assert payload["type"] == "_DummyBet"
    assert payload["amount"]["exact"] == "5/1"
    assert payload["working"] is True


def test_bet_amount_must_be_positive() -> None:
    with pytest.raises(ValueError, match="amount"):
        _DummyBet("x", Fraction(0))
    with pytest.raises(ValueError, match="amount"):
        _DummyBet("x", Fraction(-5))


def test_bet_accepts_int_amount_stored_as_fraction() -> None:
    bet = _DummyBet("x", 5)
    assert bet.amount == Fraction(5)
    assert isinstance(bet.amount, Fraction)


def test_bet_working_defaults_true_and_is_mutable() -> None:
    bet = _DummyBet("x", Fraction(5))
    assert bet.working is True
    # Bet is intentionally NON-frozen: subclasses hold mutable state.
    bet.working = False
    assert bet.working is False
