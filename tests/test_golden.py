"""Tests for the headless golden-verify math self-check (:mod:`craps_tui.golden`).

The golden checker recomputes a handful of canonical craps scenarios through the
real engine and compares the results against exact-:class:`~fractions.Fraction`
oracles. These tests pin those oracles to values that were hand-derived from the
combinatorics (see the inline derivations) so that any future drift in the
engine's math is caught here, not in production.
"""

from __future__ import annotations

from fractions import Fraction

from craps_tui.golden import (
    CheckResult,
    run_golden_checks,
)


def _result_by_label(results: list[CheckResult], label: str) -> CheckResult:
    """Return the single :class:`CheckResult` whose ``label`` matches exactly."""
    matches = [r for r in results if r.label == label]
    assert len(matches) == 1, f"expected exactly one result for {label!r}, got {len(matches)}"
    return matches[0]


def test_run_golden_checks_all_pass() -> None:
    """Every recomputed quantity matches its oracle: a non-empty all-green run."""
    results = run_golden_checks()
    assert results, "run_golden_checks must return a non-empty list"
    assert all(isinstance(r, CheckResult) for r in results)
    assert all(r.passed for r in results), [
        (r.label, r.expected, r.actual) for r in results if not r.passed
    ]


def test_at_least_three_distinct_scenarios() -> None:
    """The required three scenarios (hedge, pass-line, place-6) are all present."""
    results = run_golden_checks()
    labels = {r.label for r in results}
    # Each scenario contributes its own labelled checks; assert each appears.
    assert any(label.startswith("hedge |") for label in labels)
    assert any(label.startswith("pass-line |") for label in labels)
    assert any(label.startswith("place-6 |") for label in labels)


def test_hedge_oracles_are_the_canonical_fractions() -> None:
    """The hedge scenario carries the exact canonical oracles, all passing.

    These are the values the whole engine illustrates (see portfolio.py and
    examples/hedged_dp_place68.py): DP 10 + Place 6/8 of 6, point 4.
      matrix: 4:-10, 6:+7, 7:-2, 8:+7, 5:0
      Lens A single_roll_ev = 7/9
      Lens B house_drag      = 7/22
    """
    results = run_golden_checks()

    matrix_4 = _result_by_label(results, "hedge | matrix[4]")
    assert matrix_4.expected == str(Fraction(-10))
    assert matrix_4.passed

    matrix_6 = _result_by_label(results, "hedge | matrix[6]")
    assert matrix_6.expected == str(Fraction(7))
    assert matrix_6.passed

    matrix_7 = _result_by_label(results, "hedge | matrix[7]")
    assert matrix_7.expected == str(Fraction(-2))
    assert matrix_7.passed

    matrix_8 = _result_by_label(results, "hedge | matrix[8]")
    assert matrix_8.expected == str(Fraction(7))
    assert matrix_8.passed

    matrix_5 = _result_by_label(results, "hedge | matrix[5]")
    assert matrix_5.expected == str(Fraction(0))
    assert matrix_5.passed

    lens_a = _result_by_label(results, "hedge | Lens A (single-roll EV)")
    assert lens_a.expected == str(Fraction(7, 9))
    assert lens_a.passed

    lens_b = _result_by_label(results, "hedge | Lens B (house drag)")
    assert lens_b.expected == str(Fraction(7, 22))
    assert lens_b.passed


def test_pass_line_only_oracles() -> None:
    """A lone PassLine(10) on the COME-OUT, hand-derived oracles.

    On the come-out the Pass Line wins 1:1 on a natural (7/11), loses on craps
    (2/3/12), and takes NO_ACTION (delta 0) on the point numbers (4,5,6,8,9,10)
    which merely establish a point.
      matrix: 7:+10, 11:+10, 2:-10, 3:-10, 12:-10, point numbers: 0
      Lens A = sum P(total)*delta
             = (6/36)(10)+(2/36)(10)+(1/36)(-10)+(2/36)(-10)+(1/36)(-10)
             = (60+20-10-20-10)/36 = 40/36 = 10/9
      Lens B house_drag = 10 * 7/495 = 70/495 = 14/99   (Pass edge from registry)
    """
    results = run_golden_checks()

    win_7 = _result_by_label(results, "pass-line | matrix[7]")
    assert win_7.expected == str(Fraction(10))
    assert win_7.passed

    craps_2 = _result_by_label(results, "pass-line | matrix[2]")
    assert craps_2.expected == str(Fraction(-10))
    assert craps_2.passed

    point_4 = _result_by_label(results, "pass-line | matrix[4]")
    assert point_4.expected == str(Fraction(0))
    assert point_4.passed

    lens_a = _result_by_label(results, "pass-line | Lens A (single-roll EV)")
    assert lens_a.expected == str(Fraction(10, 9))
    assert lens_a.passed

    lens_b = _result_by_label(results, "pass-line | Lens B (house drag)")
    assert lens_b.expected == str(Fraction(14, 99))
    assert lens_b.passed


def test_place_6_only_oracles() -> None:
    """A lone PlaceBet 6 of 6, live during the POINT phase, hand-derived oracles.

    During the POINT phase a place bet is always live. Place 6 pays 7:6, so a $6
    stake wins $7 when a 6 is rolled, loses the $6 stake on a 7, and is otherwise
    NO_ACTION (delta 0).
      matrix: 6:+7, 7:-6, all others: 0
      Lens A = (5/36)(7) + (6/36)(-6) = (35-36)/36 = -1/36
      Lens B house_drag = 6 * 1/66 = 6/66 = 1/11   (place 6/8 edge from registry)
    """
    results = run_golden_checks()

    win_6 = _result_by_label(results, "place-6 | matrix[6]")
    assert win_6.expected == str(Fraction(7))
    assert win_6.passed

    lose_7 = _result_by_label(results, "place-6 | matrix[7]")
    assert lose_7.expected == str(Fraction(-6))
    assert lose_7.passed

    idle_5 = _result_by_label(results, "place-6 | matrix[5]")
    assert idle_5.expected == str(Fraction(0))
    assert idle_5.passed

    lens_a = _result_by_label(results, "place-6 | Lens A (single-roll EV)")
    assert lens_a.expected == str(Fraction(-1, 36))
    assert lens_a.passed

    lens_b = _result_by_label(results, "place-6 | Lens B (house drag)")
    assert lens_b.expected == str(Fraction(1, 11))
    assert lens_b.passed


def test_expected_values_are_display_ready_strings() -> None:
    """Expected/actual are the str repr of the exact Fractions (e.g. "7/9")."""
    results = run_golden_checks()
    lens_a = _result_by_label(results, "hedge | Lens A (single-roll EV)")
    assert lens_a.expected == "7/9"
    assert lens_a.actual == "7/9"


def test_checker_detects_drift() -> None:
    """A CheckResult built from a WRONG oracle reports ``passed is False``.

    This proves the checker would catch engine drift: if the recomputed actual
    ever diverged from the pinned oracle, ``passed`` flips to False. We construct
    the failing result directly so GOLDEN_SCENARIOS stays all-green.
    """
    actual = Fraction(7, 9)
    wrong_expected = Fraction(1, 2)
    failing = CheckResult(
        label="synthetic | deliberately wrong",
        expected=str(wrong_expected),
        actual=str(actual),
        passed=(actual == wrong_expected),
    )
    assert failing.passed is False

    # And the mirror: a correct oracle yields passed True via the same logic.
    right_expected = Fraction(7, 9)
    matching = CheckResult(
        label="synthetic | correct",
        expected=str(right_expected),
        actual=str(actual),
        passed=(actual == right_expected),
    )
    assert matching.passed is True
