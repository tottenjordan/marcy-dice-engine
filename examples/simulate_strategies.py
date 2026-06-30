"""Runnable showcase: three craps strategies raced through Monte Carlo.

The teaching point
------------------
Three classic strategies are run through the SAME deterministic Monte Carlo
batch -- identical seed, session config, and number of sessions -- so the only
thing that varies is the betting policy. Lining the aggregate stats up side by
side makes the core risk/reward trade-off visible:

* **Pass Line** -- the plainest right-way line bet. One flat 1:1 wager per
  round, the lowest exposure and the lowest variance of the three.
* **Pass + Odds** -- the same flat line backed by 1x free odds on the point.
  Free odds are a zero-edge bet, so they widen the swings (higher stdev, more
  reach toward the goal) WITHOUT adding house drag.
* **DP + Place 6/8** -- the hedged "wrong-way" showcase from
  :mod:`examples.hedged_dp_place68`: a Don't Pass line whose seven-out is hedged
  by Place 6 and Place 8. Stacking three bets smooths some swings but concedes
  multiple house edges at once.

What to read in the table
-------------------------
Compare **Risk of Ruin** (fraction of sessions that busted), **mean ending
bankroll**, **volatility** (population stdev of the ending bankroll), the
**goal-hit rate**, and the **mean rolls** per session. More chips on the felt
(odds, hedges) buy a higher chance of reaching the win goal at the price of a
higher chance of busting first -- the swings cut both ways.

This module is under ``examples/`` (not ``src/``), so printing is allowed here
and ONLY here. :func:`build_config` and :func:`build_results` are PURE (no I/O);
every ``print`` lives inside :func:`main` and the pure display helpers it calls,
keeping the engine's no-IO contract intact. The fixed seed makes the whole
comparison reproducible, which is exactly what the integration test pins.
"""

from __future__ import annotations

from fractions import Fraction
from typing import TYPE_CHECKING

from craps_engine.montecarlo import run_monte_carlo
from craps_engine.session import SessionConfig
from craps_engine.strategy import (
    DontPassPlaceStrategy,
    PassLineOddsStrategy,
    PassLineStrategy,
)

if TYPE_CHECKING:
    from collections.abc import Callable

    from craps_engine.montecarlo import MonteCarloResult
    from craps_engine.session import Strategy

# A FIXED seed makes the whole batch reproducible: every run (and the test)
# sees identical MonteCarloResults.
_SEED = 20260626

# 200 sessions is statistically plenty to make the comparison stable for this
# teaching demo while keeping the run -- and the integration test that actually
# executes it -- fast (a couple of seconds per batch).
_N_SESSIONS = 200

# Scenario knobs, chosen to make the three strategies tell DIFFERENT stories:
# a $300 bankroll with a $450 win goal (a +50% target) and a 200-roll cap is
# long enough that the higher-variance strategies can actually reach the goal --
# or bust trying -- before the roll cap stops them.
_STARTING_BANKROLL = Fraction(300)
_MAX_ROLLS = 200
_WIN_GOAL = Fraction(450)

# The strategies to race, in display order: (label, zero-arg factory). Each
# factory returns a FRESH strategy so every session starts clean.
_STRATEGIES: list[tuple[str, Callable[[], Strategy]]] = [
    ("Pass Line", lambda: PassLineStrategy(unit=10)),
    ("Pass + Odds", lambda: PassLineOddsStrategy(unit=10)),
    ("DP + Place 6/8", DontPassPlaceStrategy),
]


def build_config() -> SessionConfig:
    """Return the shared session config every strategy is measured against.

    A $300 start, $450 win goal, $0 loss limit (bust at or below zero), capped at
    200 rolls. PURE: just constructs the immutable config value.
    """
    return SessionConfig(
        starting_bankroll=_STARTING_BANKROLL,
        max_rolls=_MAX_ROLLS,
        win_goal=_WIN_GOAL,
        loss_limit=Fraction(0),
    )


def build_results() -> dict[str, MonteCarloResult]:
    """PURE: run the Monte Carlo batch for every strategy and return the results.

    Each strategy is run through :func:`run_monte_carlo` with the SAME fixed
    ``_SEED``, the shared :func:`build_config`, and ``_N_SESSIONS``, so the result
    is fully deterministic and free of any I/O. This is the structured data the
    integration test asserts against (and the table in :func:`main` renders).
    """
    config = build_config()
    return {
        label: run_monte_carlo(factory, config, _N_SESSIONS, seed=_SEED)
        for label, factory in _STRATEGIES
    }


def _format_header() -> str:
    """Return the aligned column header for the comparison table."""
    return (
        f"{'Strategy':<16}{'RoR':>8}{'Mean End':>13}"
        f"{'Volatility':>13}{'Goal Hit':>11}{'Mean Rolls':>13}"
    )


def _format_row(label: str, result: MonteCarloResult) -> str:
    """Render one strategy's aggregate stats as an aligned table row.

    ``MonteCarloResult`` is already at the sanctioned float reporting boundary, so
    the floats are formatted directly: rates as percentages, money as dollars.
    """
    return (
        f"{label:<16}"
        f"{result.risk_of_ruin:>7.1%} "
        f"{f'${result.mean_ending:,.2f}':>12} "
        f"{f'${result.stdev_ending:,.2f}':>12} "
        f"{result.goal_hit_rate:>10.1%} "
        f"{result.mean_rolls:>12.1f}"
    )


def main() -> None:
    """Print the strategy-comparison table and a short teaching note.

    All printing is confined here and to the pure ``_format_*`` helpers it calls.
    The numbers come straight from the pure :func:`build_results`, so what is
    printed is exactly what the test verifies.
    """
    results = build_results()

    print("=" * 74)
    print("Monte Carlo strategy comparison")
    print(
        f"  bankroll ${float(_STARTING_BANKROLL):,.0f} -> goal "
        f"${float(_WIN_GOAL):,.0f}, bust at $0, max {_MAX_ROLLS} rolls"
    )
    print(f"  {_N_SESSIONS} sessions per strategy, fixed seed {_SEED}")
    print("=" * 74)
    print()

    print(_format_header())
    print("-" * 74)
    for label, _ in _STRATEGIES:
        print(_format_row(label, results[label]))
    print()

    print("Read it as a risk/reward trade-off:")
    print("  * Pass Line is the lowest-exposure, lowest-volatility baseline.")
    print("  * Pass + Odds adds ZERO-edge free odds: more volatility and more")
    print("    reach toward the goal, without extra house drag.")
    print("  * DP + Place 6/8 stacks three bets -- smoother some rolls, but it")
    print("    concedes multiple house edges and shows it over the long run.")
    print("More chips working buys a higher goal-hit rate at a higher risk of ruin.")
    print("=" * 74)


if __name__ == "__main__":
    main()
