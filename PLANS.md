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
