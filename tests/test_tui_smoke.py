"""Smoke + unit tests for the Textual calculator shell.

The real logic lives in the pure helpers ``render_analysis`` and
``render_verify_lines``, which are unit-tested directly here for coverage. A
headless Pilot smoke test then drives the live app end-to-end (set Inputs ->
trigger action -> assert the results widget's rendered text) to prove the thin
Textual wiring delegates correctly.
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

from textual.widgets import Input, Static

import craps_tui.__main__ as entrypoint
from craps_tui.app import (
    CrapsCalculatorApp,
    render_analysis,
    render_verify_lines,
)
from craps_tui.golden import CheckResult, run_golden_checks

if TYPE_CHECKING:
    import pytest

# The canonical hedge: Don't Pass 10 + Place 6/8 of 6, on point 4. These exact
# substrings come from the view-model's render of that scenario.
_HEDGE_BETS = "dontpass:10, place 6:6, place 8:6"
_HEDGE_POINT = "4"
_HEDGE_SUBSTRINGS = ("4:-10", "6:+7", "7:-2", "8:+7", "7/9", "7/22")


def test_render_analysis_hedge_matches_viewmodel() -> None:
    out = render_analysis(_HEDGE_BETS, _HEDGE_POINT)
    for substring in _HEDGE_SUBSTRINGS:
        assert substring in out
    assert not out.startswith("Error:")


def test_render_analysis_empty_is_friendly() -> None:
    out = render_analysis("   ", "")
    assert "No bets entered" in out


def test_render_analysis_come_out_no_point() -> None:
    out = render_analysis("pass:10", "")
    assert out.startswith("Matrix:")


def test_render_analysis_bad_spec_returns_error() -> None:
    out = render_analysis("notabet:5", "")
    assert out.startswith("Error:")
    assert "unknown bet kind" in out


def test_render_analysis_non_numeric_point_returns_error() -> None:
    out = render_analysis("pass:10", "abc")
    assert out.startswith("Error:")
    assert "point must be" in out


def test_render_analysis_invalid_point_returns_error() -> None:
    out = render_analysis("pass:10", "7")
    assert out.startswith("Error:")
    assert "not a valid point" in out


def test_render_verify_lines_all_pass() -> None:
    checks = run_golden_checks()
    out = render_verify_lines(checks)
    assert "✗" not in out
    assert out.count("✓") == len(checks)
    assert f"{len(checks)}/{len(checks)} checks passed" in out


def test_render_verify_lines_reports_failure() -> None:
    checks = [
        CheckResult(label="ok", expected="1", actual="1", passed=True),
        CheckResult(label="bad", expected="1", actual="2", passed=False),
    ]
    out = render_verify_lines(checks)
    assert "✓ ok" in out
    assert "✗ bad  expected=1 actual=2" in out
    assert "1/2 checks passed" in out


async def _drive_app() -> tuple[str, str]:
    """Drive the live app headlessly: analyze the hedge, then verify.

    Returns the results-panel text after Analyze and after Verify so the sync
    test wrapper can assert on both without needing an async test runner.
    """
    app = CrapsCalculatorApp()
    async with app.run_test() as pilot:
        app.query_one("#bets", Input).value = _HEDGE_BETS
        app.query_one("#point", Input).value = _HEDGE_POINT
        # Click the buttons rather than press the key bindings: a focused Input
        # swallows printable keys ("a"/"v"), so the buttons are the reliable
        # headless trigger for the same action methods.
        await pilot.click("#analyze")
        await pilot.pause()
        analyzed = str(app.query_one("#results", Static).content)

        await pilot.click("#verify")
        await pilot.pause()
        verified = str(app.query_one("#results", Static).content)
    return analyzed, verified


def test_app_analyze_and_verify_headless() -> None:
    """End-to-end: the Textual key bindings wire through to the pure helpers."""
    analyzed, verified = asyncio.run(_drive_app())

    for substring in _HEDGE_SUBSTRINGS:
        assert substring in analyzed

    assert "✗" not in verified
    assert "✓" in verified
    total = len(run_golden_checks())
    assert f"{total}/{total} checks passed" in verified


def test_main_constructs_app_and_runs_once(monkeypatch: pytest.MonkeyPatch) -> None:
    """``main()`` builds the app and calls ``.run()`` exactly once (no TTY).

    ``CrapsCalculatorApp.run`` is monkeypatched to record the call instead of
    launching an interactive terminal, so this both covers the entry point and
    guards against an entry-point wiring typo.
    """
    calls: list[CrapsCalculatorApp] = []

    def _fake_run(self: CrapsCalculatorApp) -> None:
        calls.append(self)

    monkeypatch.setattr(CrapsCalculatorApp, "run", _fake_run)
    entrypoint.main()

    assert len(calls) == 1
    assert isinstance(calls[0], CrapsCalculatorApp)
