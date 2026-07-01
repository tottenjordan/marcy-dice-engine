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

## Phase 3 (play mode + web app — done)

Plan: `~/.claude/plans/gleaming-wiggling-yao.md` (approved). Interactive play + a
deployable FastAPI + HTMX web app. Order W1 → W6.

| # | Item | Status | Commit |
|---|---|---|---|
| W1 | session.py — extract per-roll settlement into `Table.settle` | ✅ Done | `6fce4e8` |
| W2 | specs.py + play.py — bet-spec module + pure `PlayController` | ✅ Done | `d1e9d15` |
| W3 | play.py — data-driven `coaching_hint` | ✅ Done | `adf76d8` |
| W4 | craps_api/ — FastAPI JSON backend + session store + `craps-web` | ✅ Done | `e5d72ac` |
| W5 | craps_api/ — HTMX browser frontend (templates + static) | ✅ Done | `aad4b80` |
| W6 | Dockerfile + deploy/docs sync (README/CLAUDE/PLANS) | ✅ Done | `2e33622` |

## Phase 4 (visual craps-table UI — in progress)

Plan: `~/.claude/plans/gleaming-wiggling-yao.md` (approved). Turn the plain board
into a visual green-felt table with clickable bet zones + chips. All work stays
in `craps_api/` (no engine changes, no new routes). Order T1 → T2 → T3.

| # | Item | Status | Commit |
|---|---|---|---|
| T1 | board.py — felt zone-keys + `chip_zones` aggregation (pure) | ✅ Done | `641bcd7` |
| T2 | _board.html + style.css — clickable felt with chips + dimmed unsupported | ✅ Done | `26e0568` |
| T3 | docs sync (README/CLAUDE) for the visual table | ➡️ Folded into Phase 5 P7 | |

## Phase 5 (play-feature upgrades — in progress)

Plan: `~/.claude/plans/gleaming-wiggling-yao.md` (approved). Uncapped play,
press/remove bet ops, and felt trackers (odds tooltips, risk total, last-10 roll
strip, per-roll net). Engine-first; `craps_api` adds thin routes + render.
Order P1 → P7. Deps: P4 needs P1+P3; P5 needs P1+P2+P3; P6 needs P4+P5; P7 last.

| # | Item | Status | Commit |
|---|---|---|---|
| P1 | engine — uncapped interactive play (optional `max_rolls`) | ✅ Done | `f8130c5` |
| P2 | engine — recent roll history on controller/view | ✅ Done | `a9d7927` |
| P3 | engine — remove + press bet operations | ✅ Done | `9e67d4d` |
| P4 | api — remove/press routes + uncapped web wiring + JSON parity | ✅ Done | `55fa8d3` |
| P5 | board — risk total, roll-net, history, odds tips, per-bet controls | ✅ Done | `29bcdfa` |
| P6 | ui — felt trackers + per-bet press/remove controls | ✅ Done | `3a830fd` |
| P7 | docs — README/CLAUDE + captured UI screenshots (absorbs T3) | ➡️ Redone as Phase 6 Q5 | |

## Phase 6 (betting guidance + felt polish — in progress)

Plan: `~/.claude/plans/gleaming-wiggling-yao.md` (approved). Act on play-mode UI
feedback: advisory optimal place-bet units (tooltip + tip, never enforced), a
point-established indicator (yellow ring + ON puck), a Net percentage, and a
wide-screen no-scroll dashboard. Engine-first for the unit math; `craps_api`
renders. Supersedes the abandoned Phase-5 P7 docs branch. Order Q1 → Q5 (linear).

| # | Item | Status | Commit |
|---|---|---|---|
| Q1 | engine — expose optimal place-bet unit (`place_unit`) | ✅ Done | `70ec326` |
| Q2 | board — `place_units` + `net_pct` pure context | ✅ Done | `1fdb015` |
| Q3 | felt — unit tooltips + tip, point ring/puck, net % render | ✅ Done | `fafdc66` |
| Q4 | layout — wide-screen no-scroll dashboard | ✅ Done | `9da746a` |
| Q5 | docs — README/CLAUDE + regenerated screenshots (redo P7) | ✅ Done | `72143c1` |

## Phase 7 (play-mode economics — done)

Post-Phase-6 play feedback: make placed stakes reflect payout ratios, and switch
the interactive bankroll to a wallet/cash model. Design note:
`docs/notes/wallet-model.md`.

| # | Item | Status | Commit |
|---|---|---|---|
| P7a | web — snap place-bet stakes to optimal units (placement + press) | ✅ Done | `2cbe555` |
| P7b | web — wallet/cash bankroll (place deducts, remove refunds; bust on net worth); at-risk = all stakes; `(off)` uses effective-live | ✅ Done | `96e1b95` |
| P7c | engine — free odds require a flat bet + enforce 3-4-5x max at placement | ✅ Done | `b0b6a52` |

## Phase 3 backlog

Future scope, deliberately out of Phase 3:

- **Installable-wheel packaging.** A built wheel currently packages only the
  `craps_engine` module (uv_build defaults the wheel to the project-name module),
  so `craps_api`/`craps_tui` and the `craps_api/templates` + `craps_api/static`
  data files are omitted. This is invisible locally (editable `.pth` install) and
  does not affect the Docker image (which runs from the synced source tree by
  design), but publishing installable wheels would need multi-module +
  data-file inclusion configured for `uv_build`.
- **Multi-instance / durable session store.** The web app's `SessionStore` is
  in-memory and single-instance (games are lost on restart, no TTL/eviction). A
  shared store (e.g. Redis) is required before horizontal scaling.
- **Richer play features.** Free odds on come / don't-come, come-point buttons, a
  free-cash / affordability bankroll model, bankroll-trajectory charts, and
  accounts/persistence.

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
