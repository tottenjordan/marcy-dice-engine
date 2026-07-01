# Play-mode wallet/cash bankroll model (approved, not yet implemented)

**Decision (user, this session):** switch the interactive PLAY experience from the
engine's net-worth bankroll to a **wallet/cash** model. Placing a bet subtracts
its stake from the displayed bankroll; removing refunds it; a win credits profit
(and returns the stake if the bet comes down); a loss keeps the already-subtracted
stake. The analyzer/Monte Carlo/portfolio stay net-worth (unchanged).

## Key identity (why this is a small change, not an engine rewrite)

```
wallet_bankroll = net_worth_bankroll − (sum of ALL active bet stakes on the table)
at_risk        = sum of ALL active bet stakes on the table
=> wallet_bankroll + at_risk == net_worth_bankroll   (always)
```

The whole net-worth engine (`session.py` `Table.settle: bankroll += delta`,
`run_session`, `montecarlo`, `portfolio`, `golden`) stays UNTOUCHED. Only the
interactive play VIEW (`PlayController.snapshot`) and the web board change.

## Design (exact)

- `PlayController.snapshot()` (play.py ~223):
  - `on_table = sum(bet.amount for bet in self._table.active_bets())`
  - `wallet = self._table.bankroll - on_table`
  - `bankroll = wallet`
  - `running_net = wallet - starting`   (so net moves on place/remove too — this is
    what the user explicitly wants: "remove a bet → net AND bankroll increase")
- **Game-over stays on NET WORTH** (`_check_game_over` keeps using
  `self._table.bankroll`): you're not bust just because chips are on the felt.
- `board.py`:
  - `total_at_risk` = sum of ALL active bet amounts (NOT just `working`). This makes
    `bankroll + at_risk == net worth` and also fixes the separate display bug below.
  - Per-bet `(off)` label: use EFFECTIVE-LIVE, not the raw `working` flag. A Place
    bet is live during the point regardless of `working` (see
    `PlaceBet._is_live`: live iff `phase is POINT or working`). So during the point
    a place bet must NOT render `(off)`. Add a `live` field to the BetRow (or
    compute in board): `live = working or (type == "PlaceBet" and phase == "point")`.
  - `last_roll_net`: LEAVE AS-IS (sum of resolution deltas = the roll's action
    P&L). It answers "what did this roll do" and is intuitive; it can diverge from
    the running_net change on line-bet resolutions (stake moving on/off table) —
    accepted. Revisit only if the user dislikes it.

## Trace to verify against (start $300)

```
place pass $10 + place 6 $12   bankroll 278  net -22  at_risk 22   (net_worth 300)
roll 8 → point                 bankroll 278  net -22  at_risk 22
roll 6 → place 6 wins +14      bankroll 292  net  -8  at_risk 22   (net_worth 314)
roll 8 → point made, pass wins bankroll 324  net +24  at_risk 12   (pass came down; net_worth 324)
```
(Remove a bet → bankroll and net both go UP by its stake; at_risk goes down.)

## Already verified this session (NOT a bug)

Winnings during a point ARE credited correctly under the current net-worth model
(place 6 win: 300→314; point made pass win: 314→324). The user's confusion was the
model, not a math bug.

## Separate display bug (fix as part of this)

During the point, a Place bet is live but the board showed it `(off)` and left it
OUT of the At-risk badge (raw `working=False`). Fixed by the two board.py changes
above (at_risk sums all stakes; `(off)` uses effective-live).

## Task list / footprint

1. play.py snapshot → wallet bankroll + net; docstring explaining the wallet view.
2. board.py → total_at_risk sums all stakes; add `live` to BetRow; template `(off)`
   uses `live`.
3. Tests: test_play.py (bankroll after place/remove/win/lose), test_htmx.py
   (total_at_risk now includes off/all bets; `(off)` label during point; wallet
   bankroll/net display), test_api.py (bankroll/net semantics now wallet).
   Update the two existing at-risk tests (`test_total_at_risk_sums_only_working_bets_exactly`,
   `test_total_at_risk_excludes_non_working_bet`) to the new "all stakes" semantics.
4. Docs: README "Web app" section (explain wallet model + bankroll+at_risk=net
   worth); CLAUDE.md if it describes accounting; play.py snapshot docstring.
   session.py net-worth docstring stays accurate (engine IS still net-worth).
5. Regenerate screenshots (docs/capture_screenshots.py) — bankroll/at-risk numbers change.
6. Quality gate green; commit `feat(web): wallet/cash bankroll for interactive play`.

## Standing constraints (unchanged)

uv only; explicit-path staging (never `git add -A`); no Co-Authored-By trailer;
per-feature branch or direct-to-main iterative (recent tweaks went direct to main
with the gate green). Push after gate passes.
