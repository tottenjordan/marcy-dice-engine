# Code Standards

These standards are binding for all code and environment changes in this repo.
Consult this document before writing code or changing tooling.

## Package management

- **uv only.** Never invoke bare `pip` or `python`. All commands run through `uv run`.
- Add dependencies with `uv add` (or `uv add --group <group>` for a dependency
  group). Never edit dependency entries in `pyproject.toml` by hand.

## Lint & format

- **ruff** for both formatting and linting:
  - `uv run ruff format`
  - `uv run ruff check`
- Never use black, flake8, or isort.

## Type checking

- **ty**: `uv run ty check src/`
- Not mypy, not pyright.

## Testing

- **pytest** + **pytest-cov**.
- Coverage threshold: **≥ 90%**.
- **TDD**: write the failing test first, then make it pass.

## Money & odds

- ALL monetary, odds, and EV values use `fractions.Fraction` internally for
  exact math. No floats in the engine's arithmetic.
- Floats appear only at the display boundary, via the central serializer in
  `craps_engine.money`.

## Engine purity

- NO `print` or other I/O inside `src/craps_engine/`.
- Engine methods return structured data. Only code under `examples/` formats
  and prints.

## Serialization

- Domain dataclasses expose `to_dict()`.
- Fractions serialize via `serialize_fraction` (producing exact + float +
  display forms) so a future UI / Monte-Carlo layer consumes one shape.

## Typing

- Full type hints everywhere.

## Commits

- Use [Conventional Commits](https://www.conventionalcommits.org/) style.
- **NEVER add `Co-Authored-By` trailers.**

## Exact craps math reference table

This table is the canonical test-oracle source. Tests assert against these
exact values.

| Bet | Payout (win:stake) | House edge (exact) | ≈ % |
|---|---|---|---|
| Pass Line | 1:1 | `7/495` | 1.414% |
| Don't Pass (bar 12) | 1:1 | `3/220` | 1.364% |
| Free Odds (take/lay) | true odds | `0` | 0% |
| Place 6 / 8 | 7:6 | `1/66` | 1.515% |
| Place 5 / 9 | 7:5 | `1/25` | 4.000% |
| Place 4 / 10 | 9:5 | `1/15` | 6.667% |
| Place 2 / 12 (crapless) | 11:2 | `1/14` | 7.143% |
| Place 3 / 11 (crapless) | 11:4 | `1/16` | 6.250% |

The crapless place bets both carry a per-roll edge of exactly `1/72`.

True odds ratios (number → win:stake): take (Pass) 4/10→2:1, 5/9→3:2, 6/8→6:5,
and the crapless points 2/12→6:1, 3/11→3:1; lay (Don't Pass) is the inverse
(4/10→1:2, 5/9→2:3, 6/8→5:6). Dice-total probabilities over 36 combos: 2:1, 3:2,
4:3, 5:4, 6:5, 7:6, 8:5, 9:4, 10:3, 11:2, 12:1.
