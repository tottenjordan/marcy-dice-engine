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
| 8 | bets/line.py — Pass Line & Don't Pass | ⬜ Pending | |
| 9 | bets/odds.py — Free Odds (take/lay) | ⬜ Pending | |
| 10 | bets/place.py — Place 4/5/6/8/9/10 | ⬜ Pending | |
| 11 | portfolio.py — PortfolioAnalyzer (dual-lens) | ⬜ Pending | |
| 12 | examples/ — hedged demo + integration test | ⬜ Pending | |
| 13 | Final quality gate + docs sync | ⬜ Pending | |

Status legend: ✅ Done · 🚧 In progress · ⬜ Pending. Commit = short SHA of the commit completing the item.
