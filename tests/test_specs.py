"""Tests for the engine-owned bet-spec module: parsing and bet construction.

These moved out of ``craps_tui`` into :mod:`craps_engine.specs` so the engine is
the single source of truth for the human bet grammar. They cover parse
round-trips (bare and numbered kinds), the error paths, and that
:func:`build_bet` produces the right concrete :class:`Bet` subclass with the
supplied id.
"""

from __future__ import annotations

from fractions import Fraction

import pytest

from craps_engine.bets.come import ComeBet, DontCome
from craps_engine.bets.line import DontPass, PassLine
from craps_engine.bets.odds import LayOdds, TakeOdds
from craps_engine.bets.place import PlaceBet
from craps_engine.specs import BetSpec, build_bet, parse_bet_spec

# --- parse_bet_spec: happy paths -------------------------------------------


def test_parse_place_with_number() -> None:
    assert parse_bet_spec("place 6:6") == BetSpec(kind="place", amount=6, number=6)


def test_parse_pass() -> None:
    assert parse_bet_spec("pass:10") == BetSpec(kind="pass", amount=10, number=None)


def test_parse_dontpass() -> None:
    assert parse_bet_spec("dontpass:10") == BetSpec(kind="dontpass", amount=10, number=None)


def test_parse_come_bare() -> None:
    assert parse_bet_spec("come:5") == BetSpec(kind="come", amount=5, number=None)


def test_parse_dontcome_bare() -> None:
    assert parse_bet_spec("dontcome:5") == BetSpec(kind="dontcome", amount=5, number=None)


def test_parse_take() -> None:
    assert parse_bet_spec("take 4:10") == BetSpec(kind="take", amount=10, number=4)


def test_parse_lay() -> None:
    assert parse_bet_spec("lay 10:20") == BetSpec(kind="lay", amount=20, number=10)


def test_parse_is_case_insensitive_and_whitespace_tolerant() -> None:
    assert parse_bet_spec("  PLACE  8 : 6 ") == BetSpec(kind="place", amount=6, number=8)


# --- parse_bet_spec: error paths -------------------------------------------


def test_parse_pass_with_number_raises() -> None:
    with pytest.raises(ValueError, match="number"):
        parse_bet_spec("pass 6:10")


def test_parse_place_invalid_number_raises() -> None:
    with pytest.raises(ValueError, match="7"):
        parse_bet_spec("place 7:6")


def test_parse_unknown_kind_raises() -> None:
    with pytest.raises(ValueError, match="unknown bet kind"):
        parse_bet_spec("fieldbet:10")


def test_parse_negative_amount_raises() -> None:
    with pytest.raises(ValueError, match="amount"):
        parse_bet_spec("pass:-5")


def test_parse_zero_amount_raises() -> None:
    with pytest.raises(ValueError, match="amount"):
        parse_bet_spec("pass:0")


def test_parse_place_without_number_raises() -> None:
    with pytest.raises(ValueError, match="number"):
        parse_bet_spec("place:6")


def test_parse_no_colon_raises() -> None:
    with pytest.raises(ValueError, match="parse"):
        parse_bet_spec("pass10")


def test_parse_empty_kind_raises() -> None:
    with pytest.raises(ValueError, match="missing bet kind"):
        parse_bet_spec(" :10")


def test_parse_non_integer_amount_raises() -> None:
    with pytest.raises(ValueError, match="amount"):
        parse_bet_spec("pass:ten")


def test_parse_non_integer_number_raises() -> None:
    with pytest.raises(ValueError, match="integer"):
        parse_bet_spec("place x:6")


def test_parse_too_many_tokens_raises() -> None:
    with pytest.raises(ValueError, match="too many tokens"):
        parse_bet_spec("place 6 extra:6")


# --- build_bet: the right concrete subclass with the given id --------------


def test_build_bet_pass() -> None:
    bet = build_bet(BetSpec("pass", 10), "pass-x")
    assert isinstance(bet, PassLine)
    assert bet.id == "pass-x"
    assert bet.amount == Fraction(10)


def test_build_bet_dontpass() -> None:
    bet = build_bet(BetSpec("dontpass", 10), "dp0")
    assert isinstance(bet, DontPass)
    assert bet.id == "dp0"


def test_build_bet_come() -> None:
    bet = build_bet(BetSpec("come", 5), "c0")
    assert isinstance(bet, ComeBet)
    assert bet.id == "c0"


def test_build_bet_dontcome() -> None:
    bet = build_bet(BetSpec("dontcome", 5), "dc0")
    assert isinstance(bet, DontCome)
    assert bet.id == "dc0"


def test_build_bet_place() -> None:
    bet = build_bet(BetSpec("place", 6, number=6), "p0")
    assert isinstance(bet, PlaceBet)
    assert bet.id == "p0"
    assert bet.number == 6
    assert bet.amount == Fraction(6)


def test_build_bet_take() -> None:
    bet = build_bet(BetSpec("take", 10, number=4), "t0")
    assert isinstance(bet, TakeOdds)
    assert bet.id == "t0"
    assert bet.number == 4


def test_build_bet_lay() -> None:
    bet = build_bet(BetSpec("lay", 20, number=10), "l0")
    assert isinstance(bet, LayOdds)
    assert bet.id == "l0"
    assert bet.number == 10
