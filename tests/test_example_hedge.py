"""Integration test keeping the runnable hedge demo honest.

The :mod:`examples.hedged_dp_place68` module is the canonical worked example the
whole engine was built to illustrate (Don't Pass 10 hedged with Place 6 / 8 of 6
each, point established at 4). This test imports that module and asserts its
PURE :func:`build_report` output matches the Task 11 exact oracles -- the same
Fractions the portfolio tests assert -- so the demo can never drift away from the
real math. It deliberately asserts ONLY the structured data (exact-string
fields), never the printed text formatting, which is brittle. A single call to
``main()`` is exercised via ``capsys`` purely to guard against runtime errors in
the human-readable breakdown.
"""

from __future__ import annotations

from fractions import Fraction
from typing import TYPE_CHECKING

from examples.hedged_dp_place68 import build_report, main

if TYPE_CHECKING:
    import pytest

# The worked-example oracles (exact Fractions), mirroring tests/test_portfolio.py.
_MATRIX_ORACLES = {
    4: Fraction(-10),
    5: Fraction(0),
    6: Fraction(7),
    7: Fraction(-2),
    8: Fraction(7),
}


def test_report_matrix_matches_oracles() -> None:
    report = build_report()
    matrix = report["matrix"]
    for total, expected in _MATRIX_ORACLES.items():
        payload = matrix[total]
        # Reconstruct the exact Fraction from the serialized "exact" string and
        # compare to the oracle -- exact math, no float comparison.
        num, denom = payload["exact"].split("/")
        assert Fraction(int(num), int(denom)) == expected


def test_report_single_roll_ev_is_seven_ninths() -> None:
    report = build_report()
    payload = report["single_roll_ev"]
    # serialize_fraction reduces 28/36 -> 7/9.
    assert payload["exact"] == "7/9"
    num, denom = payload["exact"].split("/")
    assert Fraction(int(num), int(denom)) == Fraction(7, 9)


def test_report_house_drag_is_seven_twenty_seconds() -> None:
    report = build_report()
    payload = report["house_drag"]
    assert payload["exact"] == "7/22"
    num, denom = payload["exact"].split("/")
    assert Fraction(int(num), int(denom)) == Fraction(7, 22)


def test_main_runs_and_prints(capsys: pytest.CaptureFixture[str]) -> None:
    # Smoke-test the demo end to end: it must run without raising and emit text.
    main()
    captured = capsys.readouterr()
    assert captured.out.strip()
