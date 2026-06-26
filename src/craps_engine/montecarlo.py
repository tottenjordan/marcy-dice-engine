"""Monte Carlo session simulator and risk-of-ruin aggregation.

THE FLOAT EXCEPTION (read first)
--------------------------------
The engine is exact-:class:`~fractions.Fraction` arithmetic EVERYWHERE except
this module. Monte Carlo statistics are a REPORTING / aggregation boundary --
analogous to the :func:`~craps_engine.money.serialize_fraction` display boundary
-- so plain ``float`` is the SANCTIONED type here. Each individual session still
runs in exact Fractions inside :func:`~craps_engine.session.run_session`; only
each session's ``ending_bankroll`` is converted to ``float`` for the aggregate
statistics (mean / median / stdev / percentiles). This is the one place the
no-floats rule is intentionally relaxed.

WHAT THIS MODULE DOES
---------------------
:func:`run_monte_carlo` plays ``n_sessions`` independent sessions, each from a
fresh strategy and a deterministically-derived dice seed (``seed + i``), then
folds the per-session :class:`~craps_engine.session.SessionResult` records into a
single :class:`MonteCarloResult`: risk of ruin (bust fraction), goal-hit rate,
the ending-bankroll distribution (mean / median / population stdev / a 5-number
percentile summary) and the mean roll count.
"""

from __future__ import annotations

import statistics
from dataclasses import dataclass
from typing import TYPE_CHECKING, TypedDict

from craps_engine.dice import RandomDice
from craps_engine.session import run_session

if TYPE_CHECKING:
    from collections.abc import Callable

    from craps_engine.session import SessionConfig, Strategy

# The five percentile cut points reported in the distribution summary.
_PERCENTILES = (5, 25, 50, 75, 95)
# statistics.quantiles needs at least this many data points.
_MIN_FOR_QUANTILES = 2


class MonteCarloResultPayload(TypedDict):
    """JSON-friendly serialized shape of a :class:`MonteCarloResult`.

    Every numeric field is a plain Python ``float`` (or ``int``); there is NO
    :func:`~craps_engine.money.serialize_fraction` here because this is the float
    reporting boundary. The ``pct`` mapping uses STRING keys (``"p5"`` .. ``"p95"``)
    so the payload is directly JSON-encodable.
    """

    n_sessions: int
    risk_of_ruin: float
    goal_hit_rate: float
    mean_ending: float
    median_ending: float
    stdev_ending: float
    pct: PercentilePayload
    mean_rolls: float


class PercentilePayload(TypedDict):
    """The percentile summary with JSON-safe string keys."""

    p5: float
    p25: float
    p50: float
    p75: float
    p95: float


@dataclass(frozen=True)
class MonteCarloResult:
    """Aggregate statistics over a batch of Monte Carlo sessions.

    Frozen so a result is a safe value to share / log / compare. All fields are
    floats (the sanctioned reporting-boundary exception) except the two counts.
    ``pct`` maps the integer percentiles 5/25/50/75/95 to the corresponding
    ending-bankroll value.
    """

    #: Number of sessions simulated.
    n_sessions: int
    #: Fraction of sessions that busted, in [0, 1].
    risk_of_ruin: float
    #: Fraction of sessions that hit the win goal, in [0, 1].
    goal_hit_rate: float
    #: Mean ending bankroll across all sessions.
    mean_ending: float
    #: Median ending bankroll across all sessions.
    median_ending: float
    #: Population standard deviation of ending bankrolls.
    stdev_ending: float
    #: Ending-bankroll percentiles keyed by 5/25/50/75/95.
    pct: dict[int, float]
    #: Mean number of rolls executed per session.
    mean_rolls: float

    def to_dict(self) -> MonteCarloResultPayload:
        """Serialize to a JSON-friendly shape with ``"p5"`` .. ``"p95"`` keys.

        Floats pass through unchanged (this is the float boundary -- no
        Fraction serialization), and the integer ``pct`` keys become the string
        keys the payload TypedDict declares.
        """
        return {
            "n_sessions": self.n_sessions,
            "risk_of_ruin": self.risk_of_ruin,
            "goal_hit_rate": self.goal_hit_rate,
            "mean_ending": self.mean_ending,
            "median_ending": self.median_ending,
            "stdev_ending": self.stdev_ending,
            "pct": {
                "p5": self.pct[5],
                "p25": self.pct[25],
                "p50": self.pct[50],
                "p75": self.pct[75],
                "p95": self.pct[95],
            },
            "mean_rolls": self.mean_rolls,
        }


def _percentiles(endings: list[float]) -> dict[int, float]:
    """Map 5/25/50/75/95 to ending-bankroll percentiles.

    Uses ``statistics.quantiles(..., n=100, method="inclusive")``, whose 99 cut
    points put the k-th percentile at index ``k - 1``. ``quantiles`` requires at
    least two data points, so with fewer than two endings every percentile
    collapses to the single observed value (the ``n_sessions == 1`` guard).
    """
    if len(endings) < _MIN_FOR_QUANTILES:
        only = endings[0]
        return dict.fromkeys(_PERCENTILES, only)
    cuts = statistics.quantiles(endings, n=100, method="inclusive")
    return {p: cuts[p - 1] for p in _PERCENTILES}


def run_monte_carlo(
    strategy_factory: Callable[[], Strategy],
    config: SessionConfig,
    n_sessions: int,
    *,
    seed: int,
) -> MonteCarloResult:
    """Simulate ``n_sessions`` independent sessions and aggregate the outcomes.

    Each session ``i`` gets a fresh strategy from ``strategy_factory()`` and a
    deterministically-seeded :class:`~craps_engine.dice.RandomDice` (``seed + i``),
    so the whole batch is reproducible from ``(seed, config, n_sessions)`` alone.
    Aggregation crosses the sanctioned float boundary: each session's exact
    ``ending_bankroll`` is converted to ``float`` for the distribution stats.

    Raises:
        ValueError: if ``n_sessions`` is less than 1 (fail-fast).
    """
    if n_sessions < 1:
        msg = f"n_sessions must be >= 1, got {n_sessions}"
        raise ValueError(msg)

    results = [
        run_session(RandomDice(seed=seed + i), strategy_factory(), config)
        for i in range(n_sessions)
    ]

    endings = [float(r.ending_bankroll) for r in results]
    busts = sum(int(r.busted) for r in results)
    goals = sum(int(r.hit_goal) for r in results)

    return MonteCarloResult(
        n_sessions=n_sessions,
        risk_of_ruin=busts / n_sessions,
        goal_hit_rate=goals / n_sessions,
        mean_ending=statistics.mean(endings),
        median_ending=statistics.median(endings),
        stdev_ending=statistics.pstdev(endings),
        pct=_percentiles(endings),
        mean_rolls=statistics.mean(float(r.rolls) for r in results),
    )
