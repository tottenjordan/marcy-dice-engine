# PLANS

Goal: build an exact-math craps betting-strategy engine, one reviewable task at a time.

| # | Item | Status | Commit |
|---|---|---|---|
| 1 | Scaffold uv package + tooling | ✅ Done | `743d70e` |
| 2 | Governance docs (CODE_STANDARDS, CLAUDE, PLANS, notes) | ✅ Done | `7204a1c` |
| 3 | money.py — Fraction odds + serialization | ✅ Done | `0a0c0c2, 681187d` |
| 4 | dice.py — random + deterministic dice | ✅ Done | `8bd6d0e` |
| 5 | registry.py — odds/payout/house-edge table | ✅ Done | `c556c31` |
| 6 | state.py — GameState machine | ✅ Done | `8eaf78c` |
| 7 | bets/base.py — Bet ABC + Resolution | ✅ Done | `53f02f8` |
| 8 | bets/line.py — Pass Line & Don't Pass | ✅ Done | `85fb4d3` |
| 9 | bets/odds.py — Free Odds (take/lay) | ✅ Done | `7e2654f` |
| 10 | bets/place.py — Place 4/5/6/8/9/10 | ✅ Done | `c06f940` |
| 11 | portfolio.py — PortfolioAnalyzer (dual-lens) | ✅ Done | `fe611c0` |
| 12 | examples/ — hedged demo + integration test | ✅ Done | `b663a22` |
| 13 | Final quality gate + docs sync | ✅ Done | `b7a5dea` |

Status legend: ✅ Done · 🚧 In progress · ⬜ Pending. Commit = short SHA of the commit completing the item.

## Phase 2 (in progress)

Plan: `~/.claude/plans/gleaming-wiggling-yao.md` (approved). Order A → B → C.

| # | Item | Status | Commit |
|---|---|---|---|
| A1 | bets/come.py — ComeBet traveling-state resolution | ✅ Done | `4bc171c` |
| A2 | ComeBet established play + establish_come_point mutator | ✅ Done | `02a2aa7` |
| A3 | bets/come.py — DontCome (bar 12) | ✅ Done | `5e115ce` |
| A4 | portfolio.py — register come/don't-come in house-drag | ✅ Done | `33fb818` |
| B1 | bets/base.py — lifecycle hooks (remains_on_table, advance) | ✅ Done | `2a922c1` |
| B2 | strategy.py — Strategy protocol + starter strategies | ✅ Done | `17e5cc6` |
| B3 | session.py — Table + run_session single-session runner | ✅ Done | `4f3e8c5` |
| B4 | montecarlo.py — Monte Carlo simulator + risk of ruin | ✅ Done | `57e0d90` |
| B5 | examples/simulate_strategies.py — strategy comparison demo | ✅ Done | `acd299b` |
| C1 | pyproject.toml — textual ui group, entry point, coverage | ✅ Done | `a70199a` |
| C2 | craps_tui/golden.py — golden-verify math self-check | ✅ Done | `8a0f50b` |
| C3 | craps_tui/viewmodel.py — pure view-model/formatters | ✅ Done | `94b23f5` |
| C4 | craps_tui/app.py — Textual calculator app + verify screen | ✅ Done | `07f0151` |
| C5 | docs sync — CLAUDE.md + README.md for the TUI | ✅ Done | `7477a52` |

## Phase 3 (play mode + web app — in progress)

Plan: `~/.claude/plans/gleaming-wiggling-yao.md` (approved). Interactive play + a
deployable FastAPI + HTMX web app. Order W1 → W6.

| # | Item | Status | Commit |
|---|---|---|---|
| W1 | session.py — extract per-roll settlement into `Table.settle` | ✅ Done | `6fce4e8` |
| W2 | specs.py + play.py — bet-spec module + pure `PlayController` | ✅ Done | `d1e9d15` |
| W3 | play.py — data-driven `coaching_hint` | ✅ Done | `adf76d8` |
| W4 | craps_api/ — FastAPI JSON backend + session store + `craps-web` | ⬜ Pending | |
| W5 | craps_api/ — HTMX browser frontend (templates + static) | ⬜ Pending | |
| W6 | Dockerfile + deploy/docs sync (README/CLAUDE/PLANS) | ⬜ Pending | |

## Phase 2 backlog

Future scope, deliberately out of Phase 1:

- **Come / Don't Come bet classes.** The `GameState` machine is already designed
  to admit sub-points, so these slot in without a state-model rewrite.
- **Monte Carlo engine.** 10,000-session simulation with bankroll trajectories
  and Risk of Ruin.
- **UI / visualization layer.** All engine return types are already
  serialization-ready (`to_dict` + per-module `TypedDict` payloads), so the UI
  needs no engine changes.
- **Optional bets beyond Phase 1.** Field, hardways, buy/lay with commission,
  and other proposition bets. New bet types must also be registered in
  `PortfolioAnalyzer._house_edge` so house drag stays exact.
