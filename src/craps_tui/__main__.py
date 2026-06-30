"""Console entry point for the craps TUI (``craps-tui``)."""

from __future__ import annotations

from craps_tui.app import CrapsCalculatorApp


def main() -> None:
    """Construct and run the Textual calculator app."""
    CrapsCalculatorApp().run()


if __name__ == "__main__":  # pragma: no cover - module-as-script guard
    main()
