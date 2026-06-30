"""Textual TUI calculator shell for the craps engine.

This module is a deliberately THIN shell. All real logic lives in tested pure
modules: :mod:`craps_tui.viewmodel` (parse/build/format) and
:mod:`craps_tui.golden` (the math self-check). The two non-trivial transforms
the app performs are factored into pure, module-level helpers
(:func:`render_analysis` and :func:`render_verify_lines`) so they are unit-
testable without a running Textual app; the Textual button/key handlers do
nothing but call a helper and drop the resulting string into a widget.

Interaction model
-----------------
A single-screen calculator with two ``Input`` widgets:

* **Bets** -- comma-separated bet specs, e.g. ``dontpass:10, place 6:6,
  place 8:6``. The COMMA is the only spec separator.
* **Point** -- empty for the come-out, or one of ``4 5 6 8 9 10``.

Actions (each bound to a key and a button):

* **Analyze** (``a``) -- parse the specs, build the portfolio + state, and
  render the report. Any :class:`ValueError` is caught and shown as text.
* **Verify** (``v``) -- run the golden math self-check and render pass/fail
  lines plus an ``N/N checks passed`` summary.
* **Quit** (``q`` / ``ctrl+c``).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from textual.app import App, ComposeResult
from textual.containers import Horizontal
from textual.widgets import Button, Footer, Header, Input, Static

from craps_tui.golden import run_golden_checks
from craps_tui.viewmodel import (
    build_portfolio_from_specs,
    build_state,
    format_report,
    parse_bet_spec,
)

if TYPE_CHECKING:
    from craps_tui.golden import CheckResult

# The single separator for bet specs on the bets Input (comma-separated).
_SPEC_SEPARATOR = ","


def render_analysis(bets_text: str, point_text: str) -> str:
    """Parse, build, evaluate and format a portfolio, or return an error string.

    ``bets_text`` is the raw bets Input value (comma-separated specs);
    ``point_text`` is the raw point Input value (empty = come-out, else a point
    number). This wraps the whole parse -> build -> evaluate -> format pipeline
    and converts any :class:`ValueError` into its message string, so the app can
    show problems inline instead of crashing. Pure and deterministic.
    """
    try:
        specs = [
            parse_bet_spec(chunk) for chunk in bets_text.split(_SPEC_SEPARATOR) if chunk.strip()
        ]
        if not specs:
            return "No bets entered. Type e.g. 'dontpass:10, place 6:6, place 8:6'."
        point = _parse_point(point_text)
        analyzer = build_portfolio_from_specs(specs)
        state = build_state(point)
    except ValueError as exc:
        return f"Error: {exc}"
    return format_report(analyzer.report(state))


def _parse_point(point_text: str) -> int | None:
    """Parse the point Input: empty -> ``None`` (come-out), else an int.

    Raises :class:`ValueError` (with a clear message) on a non-integer; the
    valid-point range is enforced downstream by
    :func:`craps_tui.viewmodel.build_state`.
    """
    token = point_text.strip()
    if not token:
        return None
    try:
        return int(token)
    except ValueError:
        msg = f"point must be empty or a number (4,5,6,8,9,10), got {token!r}"
        raise ValueError(msg) from None


def render_verify_lines(checks: list[CheckResult]) -> str:
    """Render golden-check results as pass/fail lines plus an ``N/N`` summary.

    Each result becomes ``✓ <label>`` when passed or
    ``✗ <label>  expected=… actual=…`` when failed. The trailing summary line
    reports how many of the total checks passed. Pure and deterministic.
    """
    lines = [
        f"✓ {check.label}"
        if check.passed
        else f"✗ {check.label}  expected={check.expected} actual={check.actual}"
        for check in checks
    ]
    passed = sum(1 for check in checks if check.passed)
    lines.append(f"{passed}/{len(checks)} checks passed")
    return "\n".join(lines)


class CrapsCalculatorApp(App[None]):
    """The single-screen craps calculator.

    The body is intentionally tiny: ``compose`` lays out the widgets and the two
    actions delegate straight to the pure helpers above. The Textual wiring is
    marked ``# pragma: no cover`` because it can only run under a live app/Pilot;
    the logic it delegates to is fully covered by the helper unit tests and the
    headless smoke test.
    """

    TITLE = "Craps Calculator"

    CSS = """
    #bets, #point {
        margin: 1 0;
    }
    #results {
        height: 1fr;
        border: round $accent;
        padding: 1;
    }
    """

    BINDINGS = [  # noqa: RUF012 (Textual's BINDINGS is a documented class attr)
        ("a", "analyze", "Analyze"),
        ("v", "verify", "Verify"),
        ("q", "quit", "Quit"),
    ]

    def compose(self) -> ComposeResult:  # pragma: no cover - Textual layout glue
        yield Header()
        yield Input(
            placeholder="bets, e.g. dontpass:10, place 6:6, place 8:6",
            id="bets",
        )
        yield Input(placeholder="point (empty = come-out, or 4 5 6 8 9 10)", id="point")
        yield Horizontal(
            Button("Analyze", id="analyze", variant="primary"),
            Button("Verify", id="verify", variant="success"),
        )
        yield Static("Enter bets and press Analyze (a), or Verify (v).", id="results")
        yield Footer()

    def on_button_pressed(  # pragma: no cover - Textual event glue
        self,
        event: Button.Pressed,
    ) -> None:
        if event.button.id == "analyze":
            self.action_analyze()
        elif event.button.id == "verify":
            self.action_verify()

    def action_analyze(self) -> None:  # pragma: no cover - thin widget wiring
        bets = self.query_one("#bets", Input).value
        point = self.query_one("#point", Input).value
        self.query_one("#results", Static).update(render_analysis(bets, point))

    def action_verify(self) -> None:  # pragma: no cover - thin widget wiring
        self.query_one("#results", Static).update(render_verify_lines(run_golden_checks()))
