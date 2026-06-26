# CLAUDE.md

> **Always consult [CODE_STANDARDS.md](./CODE_STANDARDS.md) before writing code
> or making environment changes.**

Backend engine for a craps betting-strategy analyzer / practice simulator.

## Quality gate

Run before every commit:

```bash
uv run ruff format --check && uv run ruff check && uv run ty check src/ && uv run pytest
```

## Project layout

```
src/craps_engine/
  dice.py        random + deterministic dice
  state.py       GameState machine
  registry.py    odds/payout/house-edge table
  money.py       Fraction odds + serialization
  portfolio.py   PortfolioAnalyzer (dual-lens EV)
  bets/          Bet ABC + concrete bet types
examples/        runnable demos (only place that prints/formats)
tests/           pytest suite
docs/notes/      session notes
```

## Process

- Planning is tracked in [PLANS.md](./PLANS.md).
- Session notes live in `docs/notes/`.
