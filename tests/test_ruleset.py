"""Tests for the immutable ``Ruleset`` value object + STANDARD/CRAPLESS constants."""

from __future__ import annotations

import dataclasses

import pytest

from craps_engine.ruleset import CRAPLESS, STANDARD


def test_standard_field_values() -> None:
    """STANDARD models ordinary craps: 4-10 points, 7/11 win, 2/3/12 craps, Don't on."""
    assert STANDARD.name == "standard"
    assert STANDARD.point_numbers == frozenset({4, 5, 6, 8, 9, 10})
    assert STANDARD.pass_naturals == frozenset({7, 11})
    assert STANDARD.pass_craps == frozenset({2, 3, 12})
    assert STANDARD.allow_dont is True


def test_crapless_field_values() -> None:
    """CRAPLESS: only 7 is a natural, every other total is a point, no Don't side."""
    assert CRAPLESS.name == "crapless"
    assert CRAPLESS.point_numbers == frozenset({2, 3, 4, 5, 6, 8, 9, 10, 11, 12})
    assert CRAPLESS.pass_naturals == frozenset({7})
    assert CRAPLESS.pass_craps == frozenset()
    assert CRAPLESS.allow_dont is False


def test_ruleset_is_frozen() -> None:
    """A Ruleset is immutable — assignment raises."""
    with pytest.raises(dataclasses.FrozenInstanceError):
        STANDARD.name = "mutated"  # type: ignore[misc]


def test_ruleset_is_hashable() -> None:
    """Frozen dataclass with frozenset fields is hashable (usable as a dict key)."""
    assert hash(STANDARD) != hash(CRAPLESS)
    assert {STANDARD: 1, CRAPLESS: 2}[CRAPLESS] == 2
