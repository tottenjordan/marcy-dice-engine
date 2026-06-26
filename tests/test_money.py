"""Tests for the exact-arithmetic money & odds helpers."""

from fractions import Fraction

import pytest

from craps_engine.money import RatioOdds, serialize_fraction


def test_ratio_rejects_nonpositive_stake() -> None:
    with pytest.raises(ValueError, match="stake"):
        RatioOdds(7, 0)


def test_ratio_rejects_negative_win() -> None:
    with pytest.raises(ValueError, match="win"):
        RatioOdds(-1, 6)


def test_ratio_payout_is_exact() -> None:
    assert RatioOdds(7, 6).payout(Fraction(6)) == Fraction(7)  # place 6 stake 6 -> win 7
    assert RatioOdds(9, 5).payout(Fraction(5)) == Fraction(9)


def test_serialize_fraction_shapes() -> None:
    payload = serialize_fraction(Fraction(7, 495))
    assert payload["exact"] == "7/495"
    assert payload["float"] == float(Fraction(7, 495))
    assert payload["display"] == "1.414%"  # percent display, 3 dp


def test_ratio_as_fraction() -> None:
    assert RatioOdds(7, 6).as_fraction() == Fraction(7, 6)
    assert RatioOdds(9, 5).as_fraction() == Fraction(9, 5)


def test_ratio_payout_scales_with_stake() -> None:
    # 7:6 odds on a stake of 12 should net 14.
    assert RatioOdds(7, 6).payout(Fraction(12)) == Fraction(14)


def test_ratio_to_dict() -> None:
    assert RatioOdds(9, 5).to_dict() == {"ratio": "9:5", "float": 1.8}


def test_serialize_fraction_decimal() -> None:
    payload = serialize_fraction(Fraction(7, 495), as_percent=False)
    assert payload["exact"] == "7/495"
    assert payload["float"] == float(Fraction(7, 495))
    assert payload["display"] == "0.0141"  # 4-dp decimal display


def test_serialize_fraction_integer_value() -> None:
    # An integer-valued Fraction keeps an explicit denominator of 1.
    payload = serialize_fraction(Fraction(3))
    assert payload["exact"] == "3/1"
    assert payload["display"] == "300.000%"
