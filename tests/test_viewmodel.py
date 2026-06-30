"""Tests for the pure TUI view-model: parsing, building, and formatting.

These tie the human-facing bet grammar and the rendered report text back to the
engine's canonical hedge oracle (Don't Pass 10 + Place 6/8 of 6, point 4):
matrix 4:-10 / 6:+7 / 7:-2 / 8:+7, single-roll EV 7/9, house drag 7/22.
"""

from __future__ import annotations

import pytest

from craps_engine.portfolio import PortfolioAnalyzer
from craps_engine.state import Phase
from craps_tui.viewmodel import (
    BetSpec,
    build_portfolio_from_specs,
    build_state,
    format_report,
    parse_bet_spec,
)

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


def test_parse_garbage_raises() -> None:
    with pytest.raises(ValueError, match=r"unknown|parse|invalid"):
        parse_bet_spec("garbage")


def test_parse_unknown_kind_with_colon_raises() -> None:
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


# --- build_state ------------------------------------------------------------


def test_build_state_none_is_come_out() -> None:
    state = build_state(None)
    assert state.phase is Phase.COME_OUT
    assert state.point is None


def test_build_state_point() -> None:
    state = build_state(4)
    assert state.phase is Phase.POINT
    assert state.point == 4


def test_build_state_invalid_point_raises() -> None:
    with pytest.raises(ValueError, match="point"):
        build_state(7)


# --- build_portfolio_from_specs: ties back to the oracle --------------------


def _hedge_specs() -> list[BetSpec]:
    return [
        parse_bet_spec("dontpass:10"),
        parse_bet_spec("place 6:6"),
        parse_bet_spec("place 8:6"),
    ]


def test_build_portfolio_returns_analyzer() -> None:
    assert isinstance(build_portfolio_from_specs(_hedge_specs()), PortfolioAnalyzer)


def test_build_portfolio_handles_all_kinds() -> None:
    specs = [
        parse_bet_spec("pass:10"),
        parse_bet_spec("come:5"),
        parse_bet_spec("dontcome:5"),
        parse_bet_spec("take 4:10"),
        parse_bet_spec("lay 10:20"),
    ]
    portfolio = build_portfolio_from_specs(specs)
    # A report against a point state succeeds for every constructed bet type.
    report = portfolio.report(build_state(4))
    assert len(report["bets"]) == len(specs)


def test_build_portfolio_reproduces_oracle() -> None:
    portfolio = build_portfolio_from_specs(_hedge_specs())
    report = portfolio.report(build_state(4))
    assert report["matrix"][4]["exact"] == "-10/1"
    assert report["matrix"][6]["exact"] == "7/1"
    assert report["matrix"][7]["exact"] == "-2/1"
    assert report["matrix"][8]["exact"] == "7/1"
    assert report["single_roll_ev"]["exact"] == "7/9"
    assert report["house_drag"]["exact"] == "7/22"


# --- format_report ----------------------------------------------------------


def _hedge_report() -> object:
    return build_portfolio_from_specs(_hedge_specs()).report(build_state(4))


def test_format_report_matrix_substrings() -> None:
    text = format_report(_hedge_report())  # type: ignore[arg-type]
    assert "4:-10" in text
    assert "6:+7" in text
    assert "7:-2" in text
    assert "8:+7" in text


def test_format_report_renders_zero_totals() -> None:
    text = format_report(_hedge_report())  # type: ignore[arg-type]
    assert "5:0" in text


def test_format_report_lens_a_signed() -> None:
    text = format_report(_hedge_report())  # type: ignore[arg-type]
    assert "+7/9" in text


def test_format_report_lens_b() -> None:
    text = format_report(_hedge_report())  # type: ignore[arg-type]
    assert "7/22" in text
