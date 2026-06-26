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

## Execution notes & gotchas (Phase 1 build)

Non-obvious facts discovered during the build — the would-rediscover-the-hard-way
items. Each file/flag claim below was re-verified against the tree at finalize time.

- **Single-file pytest coverage gotcha.** `pyproject.toml` sets a global
  `--cov-fail-under=90` in `[tool.pytest.ini_options] addopts`. Running a SINGLE
  test file (e.g. `uv run pytest tests/test_x.py`) still measures coverage
  package-wide but only runs that file's tests, so it SPURIOUSLY reports
  ~50-80% and exits non-zero even when that file's own tests all pass. Only the
  full `uv run pytest` is a valid coverage gate.
- **Secrets pre-commit hook.** The environment has a secret-detection pre-commit
  hook that REJECTS a commit staging an untracked `.env` (it contains
  commented-out API keys). `.env` is gitignored. Always stage explicit paths
  (`git add <files>`), never `git add -A`, or the hook blocks the commit.
- **Python 3.11 Fraction format gotcha.** `f"{some_fraction:+}"` /
  `format(Fraction, "+")` raises
  `TypeError: unsupported format string passed to Fraction.__format__`. To show a
  signed fraction, build the sign manually (`abs(value)` + an explicit `"+"`/`"-"`
  prefix). `serialize_fraction` (in `money.py`) is the single float/display
  boundary — keep Fraction exact internally everywhere else.
- **Dual-lens insight (the core teaching point).** A Don't-Pass bettor is the
  FAVORITE once a point is established (the house edge was already paid at
  come-out via the bar-12 push and the 7/11 come-out losses). So
  `PortfolioAnalyzer.single_roll_ev` (Lens A) can be POSITIVE for a hedge in the
  point phase while `house_drag` (Lens B, long-run cost) is a positive expected
  loss. Both lenses are reported precisely because they tell different,
  both-correct stories. Worked example (DP 10 + Place 6/8 of 6, point 4): per-roll
  matrix 4 -> -10, 6 -> +7, 7 -> -2, 8 -> +7; Lens A = 7/9 ≈ +0.78;
  Lens B = 7/22 ≈ 0.318.
- **Conventions worth knowing for Phase 2.** Every serializable domain value uses
  a per-module `TypedDict` payload (`FractionPayload`, `BetPayload`,
  `OddsBetPayload`, `PlaceBetPayload`, `PortfolioReport`, etc.).
  `PortfolioAnalyzer._house_edge` dispatches by concrete bet type and RAISES
  `TypeError` on unknown bet types (so drag is never silently under-counted) —
  new Phase 2 bet types MUST be added there. Place bets are OFF on the come-out by
  default (`PlaceBet(working=False)`); in the POINT phase they are live regardless
  of the flag.
- **Test/import note.** `examples/` has no `__init__.py` (ruff INP001 is
  intentionally ignored for examples). The integration test imports it as an
  implicit namespace package, which works because `tests/__init__.py` puts the
  repo root on `sys.path`.
- **MCP session config (environment).** To run this project without the
  `adk-docs` / `google-dev-knowledge` MCP servers, launch with
  `claude --strict-mcp-config --mcp-config ~/.claude/marcy-dice-mcp.json` (that
  file keeps only paperbanana + bigquery; it lives outside the repo).
