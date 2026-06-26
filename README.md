# marcy-dice-engine

Backend engine for a **craps betting-strategy analyzer & practice simulator** —
built to learn the exact odds, payouts, and house-edge mechanics of combined
(hedged) craps strategies.

The engine is a pure, I/O-free, fully type-hinted OO core. Money and odds use
`fractions.Fraction` internally for **exact** arithmetic; floats appear only at a
single serialization boundary. The engine returns structured data (no `print`) —
a thin `examples/` layer does all formatting, keeping it ready for a future UI,
CLI, or Monte Carlo layer.

## Features (Phase 1)

- **Dice** — `RandomDice(seed)` (reproducible) and `ScriptedDice` for deterministic
  scenarios, behind a `Dice` protocol.
- **GameState** — come-out / point state machine, designed to admit Come / Don't
  Come sub-points later.
- **Bet registry** — exact odds, payouts, and house edges (Pass `7/495`,
  Don't Pass `3/220`, Place `1/66` · `1/25` · `1/15`, free odds `0`), plus
  per-roll edges and the 36-combo total-probability table.
- **Bets** — Pass Line, Don't Pass (bar 12), Take/Lay free odds, Place 4–10.
- **PortfolioAnalyzer** — for a combined set of wagers it reports:
  - a **net-payout matrix** (net bankroll change per dice total 2–12), and
  - **dual-lens EV**:
    - *Lens A — single-roll EV* for the current state (the variance / hedge view), and
    - *Lens B — house drag* = Σ(amount × house-edge) (the honest long-run cost).

## Requirements

- Python ≥ 3.11
- [uv](https://docs.astral.sh/uv/) for packaging and running

## Quickstart

```bash
uv sync --all-groups
uv run python examples/hedged_dp_place68.py
```

The demo builds a hedge (Don't Pass 10 + Place 6 / Place 8, point = 4) and prints
the net-payout matrix and both EV lenses. The teaching moment: the don't-bettor
looks *favored this roll* (Lens A) yet has already conceded a fixed long-run cost
(Lens B).

```
matrix:  4: -10   6: +7   7: -2   8: +7
Lens A (single-roll EV) = 7/9
Lens B (house drag)     = 7/22
```

## Quality gate

```bash
uv run ruff format --check && uv run ruff check && uv run ty check src/ && uv run pytest
```

Currently: ruff + ty clean, 141 tests passing, 100% coverage.

## Project layout

```
src/craps_engine/
  money.py       Fraction odds + serialization
  dice.py        random + deterministic dice
  registry.py    odds/payout/house-edge table
  state.py       GameState machine
  portfolio.py   PortfolioAnalyzer (dual-lens EV)
  bets/          Bet ABC + concrete bet types
examples/        runnable demos (the only place that prints/formats)
tests/           pytest suite
docs/notes/      session notes
```

## Roadmap (Phase 2)

- Come / Don't Come bet classes
- Monte Carlo engine: bankroll trajectories + Risk of Ruin
- UI / CLI on top of the existing serialization-ready return types

## Development

Tooling: `uv` (packaging), `ruff` (lint + format), `ty` (type-check),
`pytest` + `pytest-cov` (test). See [CODE_STANDARDS.md](./CODE_STANDARDS.md) for
conventions and [PLANS.md](./PLANS.md) for task status.
