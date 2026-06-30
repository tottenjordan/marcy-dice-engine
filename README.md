# marcy-dice-engine

A **craps betting-strategy analyzer & practice simulator** — built to learn the
exact odds, payouts, and house-edge mechanics of combined (hedged) craps
strategies, then *play them out*: run deterministic sessions, race strategies
through Monte Carlo for Risk of Ruin and bankroll distributions, and explore it
all from an interactive terminal UI.

The engine is a pure, I/O-free, fully type-hinted OO core. Money and odds use
`fractions.Fraction` internally for **exact** arithmetic; floats appear only at a
single serialization boundary (and in the Monte Carlo aggregation layer). The
engine returns structured data (no `print`) — a thin `examples/` layer and a
separate `craps_tui` package do all formatting and I/O.

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

## Features (Phase 2)

- **Come / Don't Come** — traveling come-point bets (`ComeBet`, `DontCome`, bar 12
  on Don't Come), built on new `Bet` lifecycle hooks (`remains_on_table`, `advance`).
- **Strategies** — a `Strategy` protocol plus starters: `PassLineStrategy`,
  `PassLineOddsStrategy`, `DontPassPlaceStrategy`.
- **Session runner** — `Table` + `run_session`: a deterministic single-session
  play loop producing a bankroll trajectory (`SessionConfig` → `SessionResult`).
- **Monte Carlo** — `run_monte_carlo` → `MonteCarloResult`: Risk of Ruin, goal-hit
  rate, mean / median / stdev ending bankroll, percentiles, mean roll count. See
  `examples/simulate_strategies.py` (races three strategies on one seeded batch).
- **Interactive TUI** — a Textual calculator (`uv run craps-tui`) with an
  **Analyze** view (net-payout matrix + both EV lenses) and a **Verify** view
  (golden-verify math self-check).

## Requirements

- Python ≥ 3.11
- [uv](https://docs.astral.sh/uv/) for packaging and running

## Quickstart

```bash
uv sync --all-groups
uv run python examples/hedged_dp_place68.py     # static dual-lens analysis
uv run python examples/simulate_strategies.py   # Monte Carlo strategy race
uv run craps-tui                                 # interactive TUI calculator
```

The hedge demo builds a hedge (Don't Pass 10 + Place 6 / Place 8, point = 4) and
prints the net-payout matrix and both EV lenses. The teaching moment: the
don't-bettor looks *favored this roll* (Lens A) yet has already conceded a fixed
long-run cost (Lens B).

```
matrix:  4: -10   6: +7   7: -2   8: +7
Lens A (single-roll EV) = 7/9
Lens B (house drag)     = 7/22
```

## Interactive TUI

```bash
uv run craps-tui
```

Type a comma- or newline-separated set of bets and a point, then press **Analyze**
(`a`) to get the net-payout matrix and both EV lenses (Lens A / Lens B). For
example:

```
dontpass:10, place 6:6, place 8:6      point = 4
```

Press **Verify** (`v`) to run the golden math self-check (see below). `textual` is
isolated in the `ui` dependency group, so it is pulled in only by `--all-groups`
(or `--group ui`); the engine itself stays stdlib-only.

## Verify the math

Golden-verify recomputes a small set of canonical scenarios (the Don't Pass +
Place 6/8 hedge plus a lone Pass Line and a lone Place 6) through the real engine
and asserts each result equals an independently hand-derived exact `Fraction`
oracle. It runs both as `tests/test_golden.py` and behind the TUI's Verify
action, so any drift in the engine's arithmetic is caught immediately.

## Quality gate

```bash
uv run ruff format --check && uv run ruff check && uv run ty check src/ && uv run pytest
```

Currently: ruff + ty clean, 290 tests passing, 100% coverage
(across `craps_engine` + `craps_tui`).

## Project layout

```
src/craps_engine/   pure, stdlib-only engine (no I/O)
  money.py       Fraction odds + serialization
  dice.py        random + deterministic dice
  registry.py    odds/payout/house-edge table
  state.py       GameState machine
  portfolio.py   PortfolioAnalyzer (dual-lens EV)
  strategy.py    Strategy protocol + starter strategies
  session.py     Table + run_session single-session runner
  montecarlo.py  run_monte_carlo: Risk of Ruin + ending-bankroll stats
  bets/          Bet ABC (lifecycle hooks) + concrete bet types
    come.py        ComeBet + DontCome (traveling come-point bets)
src/craps_tui/      Textual UI + golden-verify (the only place textual/I/O live)
  golden.py      run_golden_checks math self-check
  viewmodel.py   pure parse/format seam over the engine
  app.py         Textual App (Analyze + Verify actions)
  __main__.py    console entry point (craps-tui)
examples/        runnable demos (the only place that prints/formats)
tests/           pytest suite
docs/notes/      session notes
```

## Roadmap (Phase 3 backlog)

- Free odds on Come / Don't Come bets
- Free-cash bankroll model (placement deduction / affordability constraints)
- Plotting or a web UI on the existing serialization-ready return types
- A strategy DSL for declaring betting policies

## Development

Tooling: `uv` (packaging), `ruff` (lint + format), `ty` (type-check),
`pytest` + `pytest-cov` (test). See [CODE_STANDARDS.md](./CODE_STANDARDS.md) for
conventions and [PLANS.md](./PLANS.md) for task status.
