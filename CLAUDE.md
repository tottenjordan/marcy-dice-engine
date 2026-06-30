# CLAUDE.md

> **Always consult [CODE_STANDARDS.md](./CODE_STANDARDS.md) before writing code
> or making environment changes.**

Craps betting-strategy analyzer & practice simulator: a pure stdlib engine
(sessions + Monte Carlo + Risk of Ruin) with an interactive Textual TUI.

## Quality gate

Run before every commit:

```bash
uv run ruff format --check && uv run ruff check && uv run ty check src/ && uv run pytest
```

## Project layout

```
src/craps_engine/   pure, stdlib-only engine (no I/O)
  dice.py        random + deterministic dice
  state.py       GameState machine
  registry.py    odds/payout/house-edge table
  money.py       Fraction odds + serialization
  portfolio.py   PortfolioAnalyzer (dual-lens EV)
  strategy.py    Strategy protocol + starter strategies
  session.py     Table + run_session deterministic single-session runner
  montecarlo.py  run_monte_carlo: Risk of Ruin + ending-bankroll stats
  bets/          Bet ABC (lifecycle hooks) + concrete bet types
    come.py        ComeBet + DontCome (traveling come-point bets)
src/craps_tui/      Textual UI + golden-verify (ONLY place textual/I/O live)
  golden.py      run_golden_checks math self-check
  viewmodel.py   pure parse/format seam over the engine
  app.py         Textual App (Analyze + Verify actions)
  __main__.py    console entry point (craps-tui)
examples/        runnable demos (only place that prints/formats)
tests/           pytest suite
docs/notes/      session notes
```

## Running the TUI

```bash
uv run craps-tui    # interactive calculator: Analyze (a) + Verify (v)
```

Golden-verify (the engine math self-check in `craps_tui/golden.py`) is exercised
by `tests/test_golden.py` and by the app's Verify action.

## Process

- Planning is tracked in [PLANS.md](./PLANS.md).
- Session notes live in `docs/notes/`.
