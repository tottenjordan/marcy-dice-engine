"""Tests for the central exact odds/payout/house-edge registry.

These assertions are exact-oracle checks: every house edge, payout ratio, and
probability must match the canonical craps math table in CODE_STANDARDS.md as an
exact :class:`~fractions.Fraction` (never a float). The registry is the math
core, so these tests guard the numbers every later module trusts.
"""

from fractions import Fraction

import pytest

from craps_engine.money import RatioOdds
from craps_engine.registry import (
    PLACE_SPECS,
    REGISTRY,
    TOTAL_PROBABILITY,
    BetSpec,
    odds_ratio,
    odds_unit,
    place_spec,
    place_unit,
    snap_to_odds_unit,
    snap_to_place_unit,
)


def test_line_house_edges_exact() -> None:
    assert REGISTRY["pass_line"].house_edge == Fraction(7, 495)
    assert REGISTRY["dont_pass"].house_edge == Fraction(3, 220)


def test_place_house_edges_exact() -> None:
    assert place_spec(6).house_edge == Fraction(1, 66)
    assert place_spec(5).house_edge == Fraction(1, 25)
    assert place_spec(4).house_edge == Fraction(1, 15)


def test_place_house_edges_symmetry() -> None:
    # 6/8, 5/9, 4/10 are mirror pairs and must carry identical edges.
    assert place_spec(8).house_edge == Fraction(1, 66)
    assert place_spec(9).house_edge == Fraction(1, 25)
    assert place_spec(10).house_edge == Fraction(1, 15)


def test_place_per_roll_edge_exact() -> None:
    assert place_spec(6).house_edge_per_roll == Fraction(1, 66) * Fraction(11, 36)
    assert place_spec(5).house_edge_per_roll == Fraction(1, 25) * Fraction(10, 36)
    assert place_spec(4).house_edge_per_roll == Fraction(1, 15) * Fraction(9, 36)


def test_place_per_roll_edge_symmetry() -> None:
    assert place_spec(8).house_edge_per_roll == Fraction(1, 66) * Fraction(11, 36)
    assert place_spec(9).house_edge_per_roll == Fraction(1, 25) * Fraction(10, 36)
    assert place_spec(10).house_edge_per_roll == Fraction(1, 15) * Fraction(9, 36)


def test_place_payouts_exact() -> None:
    assert place_spec(6).payout == RatioOdds(7, 6)
    assert place_spec(8).payout == RatioOdds(7, 6)
    assert place_spec(5).payout == RatioOdds(7, 5)
    assert place_spec(9).payout == RatioOdds(7, 5)
    assert place_spec(4).payout == RatioOdds(9, 5)
    assert place_spec(10).payout == RatioOdds(9, 5)


def test_place_unit_exact() -> None:
    # The optimal whole-dollar unit is the payout ratio's stake leg, so a
    # stake that is a multiple of it always pays whole dollars.
    assert place_unit(6) == 6
    assert place_unit(8) == 6
    assert place_unit(5) == 5
    assert place_unit(9) == 5
    assert place_unit(4) == 5
    assert place_unit(10) == 5


def test_place_unit_rejects_invalid() -> None:
    with pytest.raises(ValueError, match="place"):
        place_unit(7)


def test_snap_to_place_unit_rounds_to_nearest_multiple() -> None:
    # 6/8 snap to $6 multiples; 4/5/9/10 snap to $5 multiples.
    assert snap_to_place_unit(6, 10) == 12
    assert snap_to_place_unit(8, 10) == 12
    assert snap_to_place_unit(5, 10) == 10
    assert snap_to_place_unit(9, 10) == 10
    assert snap_to_place_unit(4, 10) == 10
    assert snap_to_place_unit(10, 10) == 10
    # Nearer to the lower multiple stays low; exact multiples are untouched.
    assert snap_to_place_unit(6, 13) == 12
    assert snap_to_place_unit(6, 30) == 30
    assert snap_to_place_unit(5, 30) == 30


def test_snap_to_place_unit_ties_round_up() -> None:
    # Exactly halfway between two multiples rounds UP to the larger.
    assert snap_to_place_unit(6, 9) == 12  # 9 is halfway between 6 and 12
    assert snap_to_place_unit(6, 15) == 18  # halfway between 12 and 18


def test_snap_to_place_unit_floors_at_one_unit() -> None:
    # A positive stake below one unit never snaps to $0.
    assert snap_to_place_unit(6, 1) == 6
    assert snap_to_place_unit(6, 6) == 6
    assert snap_to_place_unit(5, 2) == 5


def test_snap_to_place_unit_rejects_invalid() -> None:
    with pytest.raises(ValueError, match="place"):
        snap_to_place_unit(7, 10)


def test_odds_unit_exact() -> None:
    # The optimal whole-dollar odds unit is the true-odds ratio's stake leg, so a
    # stake that is a multiple of it always pays whole dollars. Take odds pay the
    # true odds (4/10 -> 2:1, 5/9 -> 3:2, 6/8 -> 6:5); lay odds the inverse.
    assert odds_unit(take=True, number=4) == 1
    assert odds_unit(take=True, number=10) == 1
    assert odds_unit(take=True, number=5) == 2
    assert odds_unit(take=True, number=9) == 2
    assert odds_unit(take=True, number=6) == 5
    assert odds_unit(take=True, number=8) == 5
    # Lay odds are the inverse ratio, so the stake leg is the win leg of take.
    assert odds_unit(take=False, number=4) == 2
    assert odds_unit(take=False, number=10) == 2
    assert odds_unit(take=False, number=5) == 3
    assert odds_unit(take=False, number=9) == 3
    assert odds_unit(take=False, number=6) == 6
    assert odds_unit(take=False, number=8) == 6


def test_odds_unit_rejects_invalid() -> None:
    with pytest.raises(ValueError, match="point"):
        odds_unit(take=True, number=7)


def test_snap_to_odds_unit_rounds_to_nearest_multiple() -> None:
    # 6/8 take odds snap to $5 multiples; 5/9 to $2; 4/10 to $1 (a no-op).
    assert snap_to_odds_unit(take=True, number=6, amount=7) == 5
    assert snap_to_odds_unit(take=True, number=6, amount=8) == 10
    assert snap_to_odds_unit(take=True, number=5, amount=7) == 8
    assert snap_to_odds_unit(take=True, number=4, amount=7) == 7
    # Lay odds snap to their inverse-ratio stake leg (6/8 -> $6, 5/9 -> $3).
    assert snap_to_odds_unit(take=False, number=6, amount=7) == 6
    assert snap_to_odds_unit(take=False, number=5, amount=7) == 6


def test_snap_to_odds_unit_ties_round_up() -> None:
    # Exactly halfway between two multiples rounds UP to the larger.
    assert snap_to_odds_unit(take=True, number=5, amount=1) == 2  # floors at one unit
    assert snap_to_odds_unit(take=True, number=6, amount=15) == 15  # exact multiple stays


def test_snap_to_odds_unit_floors_at_one_unit() -> None:
    # A positive stake below one unit never snaps to $0.
    assert snap_to_odds_unit(take=True, number=6, amount=1) == 5
    assert snap_to_odds_unit(take=False, number=6, amount=1) == 6


def test_snap_to_odds_unit_rejects_invalid() -> None:
    with pytest.raises(ValueError, match="point"):
        snap_to_odds_unit(take=True, number=7, amount=10)


def test_place_spec_keys() -> None:
    assert place_spec(6).key == "place_6"
    assert place_spec(10).key == "place_10"


def test_place_specs_mapping_complete() -> None:
    # Every total but the 7 is placeable (the 2/3/11/12 entries serve crapless).
    assert set(PLACE_SPECS) == {2, 3, 4, 5, 6, 8, 9, 10, 11, 12}


def test_line_payouts_are_even_money() -> None:
    assert REGISTRY["pass_line"].payout == RatioOdds(1, 1)
    assert REGISTRY["dont_pass"].payout == RatioOdds(1, 1)


def test_line_specs_have_no_per_roll_edge() -> None:
    assert REGISTRY["pass_line"].house_edge_per_roll is None
    assert REGISTRY["dont_pass"].house_edge_per_roll is None


def test_take_and_lay_odds_ratios() -> None:
    assert odds_ratio(take=True, number=4).as_fraction() == Fraction(2, 1)
    assert odds_ratio(take=False, number=4).as_fraction() == Fraction(1, 2)
    assert odds_ratio(take=True, number=6).as_fraction() == Fraction(6, 5)
    assert odds_ratio(take=False, number=6).as_fraction() == Fraction(5, 6)


def test_take_and_lay_odds_ratios_5_9() -> None:
    assert odds_ratio(take=True, number=5).as_fraction() == Fraction(3, 2)
    assert odds_ratio(take=False, number=5).as_fraction() == Fraction(2, 3)
    assert odds_ratio(take=True, number=9).as_fraction() == Fraction(3, 2)
    assert odds_ratio(take=False, number=9).as_fraction() == Fraction(2, 3)


def test_take_and_lay_are_inverses() -> None:
    for number in (4, 5, 6, 8, 9, 10):
        take = odds_ratio(take=True, number=number).as_fraction()
        lay = odds_ratio(take=False, number=number).as_fraction()
        assert take * lay == Fraction(1)


def test_take_odds_10_matches_4() -> None:
    # 10 mirrors 4 (both pay true 2:1 on the take side).
    assert odds_ratio(take=True, number=10).as_fraction() == Fraction(2, 1)
    assert odds_ratio(take=True, number=8).as_fraction() == Fraction(6, 5)


def test_total_probability_sums_to_one() -> None:
    assert sum(TOTAL_PROBABILITY.values()) == Fraction(1)
    assert TOTAL_PROBABILITY[7] == Fraction(6, 36)
    assert TOTAL_PROBABILITY[2] == Fraction(1, 36)


def test_total_probability_full_table() -> None:
    ways = {
        2: 1,
        3: 2,
        4: 3,
        5: 4,
        6: 5,
        7: 6,
        8: 5,
        9: 4,
        10: 3,
        11: 2,
        12: 1,
    }
    expected = {total: Fraction(w, 36) for total, w in ways.items()}
    assert expected == TOTAL_PROBABILITY


def test_place_spec_rejects_invalid() -> None:
    with pytest.raises(ValueError, match="place"):
        place_spec(7)


def test_place_spec_rejects_seven_specifically() -> None:
    with pytest.raises(ValueError, match="7"):
        place_spec(7)


def test_odds_ratio_rejects_invalid_point() -> None:
    # 7 is the only total that is never a point (crapless makes 2/3/11/12 points).
    with pytest.raises(ValueError, match="point"):
        odds_ratio(take=True, number=7)
    with pytest.raises(ValueError, match="point"):
        odds_ratio(take=False, number=7)


def test_betspec_to_dict_line_shape() -> None:
    payload = REGISTRY["pass_line"].to_dict()
    assert payload["key"] == "pass_line"
    assert payload["payout"] == {"ratio": "1:1", "float": 1.0}
    assert payload["house_edge"]["exact"] == "7/495"
    assert payload["house_edge_per_roll"] is None


def test_betspec_to_dict_place_shape() -> None:
    payload = place_spec(6).to_dict()
    assert payload["key"] == "place_6"
    assert payload["payout"] == {"ratio": "7:6", "float": float(Fraction(7, 6))}
    assert payload["house_edge"]["exact"] == "1/66"
    assert payload["house_edge_per_roll"] is not None
    per_roll = Fraction(1, 66) * Fraction(11, 36)
    assert payload["house_edge_per_roll"]["exact"] == (
        f"{per_roll.numerator}/{per_roll.denominator}"
    )


def test_betspec_is_frozen() -> None:
    spec = REGISTRY["pass_line"]
    assert isinstance(spec, BetSpec)
    with pytest.raises(AttributeError):
        spec.key = "mutated"  # type: ignore[misc]


# ---------------------------------------------------------------------------
# Crapless craps: 2/3/11/12 become point/place/odds numbers. All values are
# exact Fractions verified against the Wizard of Odds crapless tables.
# ---------------------------------------------------------------------------
def test_crapless_take_odds_ratios() -> None:
    # True odds P(7):P(number): 2/12 -> 6:1, 3/11 -> 6:2 = 3:1 (zero edge).
    assert odds_ratio(take=True, number=2).as_fraction() == Fraction(6, 1)
    assert odds_ratio(take=True, number=12).as_fraction() == Fraction(6, 1)
    assert odds_ratio(take=True, number=3).as_fraction() == Fraction(3, 1)
    assert odds_ratio(take=True, number=11).as_fraction() == Fraction(3, 1)


def test_crapless_lay_odds_are_inverses() -> None:
    for number in (2, 3, 11, 12):
        take = odds_ratio(take=True, number=number).as_fraction()
        lay = odds_ratio(take=False, number=number).as_fraction()
        assert take * lay == Fraction(1)


def test_crapless_place_payouts_exact() -> None:
    assert place_spec(2).payout == RatioOdds(11, 2)
    assert place_spec(12).payout == RatioOdds(11, 2)
    assert place_spec(3).payout == RatioOdds(11, 4)
    assert place_spec(11).payout == RatioOdds(11, 4)


def test_crapless_place_house_edges_exact() -> None:
    assert place_spec(2).house_edge == Fraction(1, 14)
    assert place_spec(12).house_edge == Fraction(1, 14)
    assert place_spec(3).house_edge == Fraction(1, 16)
    assert place_spec(11).house_edge == Fraction(1, 16)


def test_crapless_place_per_roll_edge_is_one_seventysecond() -> None:
    # Per-roll edge = edge x P(resolve). 2/12: 1/14 x 7/36 = 1/72; 3/11: 1/16 x 8/36 = 1/72.
    for number in (2, 3, 11, 12):
        assert place_spec(number).house_edge_per_roll == Fraction(1, 72)


def test_crapless_place_unit_from_ratio_stake_leg() -> None:
    # Stake leg of the payout ratio: 2/12 pays 11:2 -> unit 2; 3/11 pays 11:4 -> unit 4.
    assert place_unit(2) == 2
    assert place_unit(12) == 2
    assert place_unit(3) == 4
    assert place_unit(11) == 4


def test_crapless_take_odds_unit_is_one() -> None:
    # 2/12 (6:1) and 3/11 (3:1) both have a $1 stake leg on the take side.
    for number in (2, 3, 11, 12):
        assert odds_unit(take=True, number=number) == 1


def test_crapless_lay_odds_unit_is_win_leg_of_take() -> None:
    # Lay is the inverse: 2/12 -> 1:6 (unit 6), 3/11 -> 1:3 (unit 3).
    assert odds_unit(take=False, number=2) == 6
    assert odds_unit(take=False, number=12) == 6
    assert odds_unit(take=False, number=3) == 3
    assert odds_unit(take=False, number=11) == 3


def test_crapless_place_spec_keys() -> None:
    assert place_spec(2).key == "place_2"
    assert place_spec(11).key == "place_11"
