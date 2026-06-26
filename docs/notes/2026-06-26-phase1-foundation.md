# 2026-06-26 — Phase 1 Foundation

Session notes: decisions and non-obvious facts that outlive the conversation
and are not recoverable from code or git history.

## Settled design decisions

- **Exact math.** Money and odds are `fractions.Fraction` internally; floats
  only at the display boundary.
- **Dual-lens EV.** `PortfolioAnalyzer` reports TWO expected-value lenses:
  - **(A) Single-roll EV** for the current game state — the variance / hedge
    view, "what happens on the next roll given where we are."
  - **(B) house_drag** = Σ(amount × house_edge) — the long-run cost view,
    "what the wagers cost over many resolutions."
- **Deferred to Phase 2:** Come / Don't Come bet classes; Monte Carlo and
  Risk-of-Ruin simulation; the UI itself.
- **UI-ready now.** Even though the UI is deferred, all engine return types are
  kept serializable / UI-ready so the future layer needs no engine changes.

## Configurable craps defaults

- Don't Pass **bars 12** (push on a come-out 12).
- Free Odds: **3-4-5×** maximum.
- Place bets are **OFF on the come-out** by default.
- True odds: **2:1 / 3:2 / 6:5** on 4-10 / 5-9 / 6-8.
- Place payouts: **9:5 / 7:5 / 7:6** on 4-10 / 5-9 / 6-8.

## Non-obvious setup facts (from Task 1)

- Toolchain versions: uv 0.9.14, ruff 0.15.20, ty 0.0.54, pytest 9.1.1,
  CPython 3.11.14.
- The engine is **stdlib-only** — no runtime dependencies.
- The uv-generated `[project.scripts]` entry was **removed** because the sample
  `main()` was deleted.
- `.python-version` is pinned to **3.11**.

## Key insight worth recording

A Don't Pass bettor is actually **FAVORED once a point is established** — the
house edge is paid up front at the come-out, after which the don't bettor has
the mathematical advantage. This is exactly why the dual-lens EV matters: the
hedge demo shows a **positive single-roll EV** (lens A) alongside a **negative
long-run house_drag** (lens B). The two numbers describe different questions and
must not be conflated.
