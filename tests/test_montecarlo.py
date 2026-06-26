"""Tests for the Monte Carlo simulator and risk-of-ruin aggregation.

These exercise ``run_monte_carlo`` and ``MonteCarloResult``: seed-driven
reproducibility, the [0,1] bounds on risk-of-ruin / goal-hit-rate, a
provably-certain-bust config (RoR == 1.0), percentile ordering, the
single-session quantiles guard, fail-fast validation, and the ``to_dict``
float/string-key serialization shape.

This module sits on the FLOAT REPORTING BOUNDARY (see the module docstring of
``craps_engine.montecarlo``), so aggregate statistics are plain floats here.
"""

from __future__ import annotations

from fractions import Fraction

import pytest

from craps_engine.montecarlo import MonteCarloResult, run_monte_carlo
from craps_engine.session import SessionConfig
from craps_engine.strategy import PassLineStrategy


def _normal_config() -> SessionConfig:
    return SessionConfig(
        starting_bankroll=Fraction(500),
        max_rolls=50,
        win_goal=Fraction(700),
        loss_limit=Fraction(0),
    )


def test_reproducible_same_seed() -> None:
    config = _normal_config()
    a = run_monte_carlo(lambda: PassLineStrategy(unit=10), config, 100, seed=7)
    b = run_monte_carlo(lambda: PassLineStrategy(unit=10), config, 100, seed=7)
    assert a == b


def test_rates_in_unit_interval() -> None:
    result = run_monte_carlo(lambda: PassLineStrategy(unit=10), _normal_config(), 200, seed=3)
    assert 0.0 <= result.risk_of_ruin <= 1.0
    assert 0.0 <= result.goal_hit_rate <= 1.0


def test_guaranteed_ruin_gives_ror_one() -> None:
    # loss_limit set absurdly high (above any reachable bankroll) so the
    # bust check ``bankroll <= loss_limit`` is true after the very first roll
    # regardless of the outcome: every session busts -> RoR == 1.0.
    config = SessionConfig(
        starting_bankroll=Fraction(100),
        max_rolls=50,
        loss_limit=Fraction(10**9),
    )
    result = run_monte_carlo(lambda: PassLineStrategy(unit=10), config, 50, seed=1)
    assert result.risk_of_ruin == 1.0


def test_n_sessions_honored() -> None:
    n = 200
    result = run_monte_carlo(lambda: PassLineStrategy(unit=10), _normal_config(), n, seed=11)
    assert result.n_sessions == n


def test_different_seeds_vary() -> None:
    config = _normal_config()
    a = run_monte_carlo(lambda: PassLineStrategy(unit=10), config, 100, seed=1)
    b = run_monte_carlo(lambda: PassLineStrategy(unit=10), config, 100, seed=999)
    assert a != b


def test_percentile_ordering() -> None:
    result = run_monte_carlo(lambda: PassLineStrategy(unit=10), _normal_config(), 200, seed=42)
    assert result.pct[5] <= result.pct[25] <= result.pct[50] <= result.pct[75] <= result.pct[95]


def test_single_session_guard() -> None:
    result = run_monte_carlo(lambda: PassLineStrategy(unit=10), _normal_config(), 1, seed=5)
    assert result.n_sessions == 1
    only = result.mean_ending
    assert result.median_ending == only
    assert result.stdev_ending == 0.0
    for key in (5, 25, 50, 75, 95):
        assert result.pct[key] == only


def test_n_sessions_zero_raises() -> None:
    config = _normal_config()
    with pytest.raises(ValueError, match="0"):
        run_monte_carlo(lambda: PassLineStrategy(unit=10), config, 0, seed=1)


def test_to_dict_shape() -> None:
    result = run_monte_carlo(lambda: PassLineStrategy(unit=10), _normal_config(), 50, seed=2)
    payload = result.to_dict()
    assert payload["n_sessions"] == 50
    pct = payload["pct"]
    assert isinstance(pct["p5"], float)
    assert isinstance(pct["p25"], float)
    assert isinstance(pct["p50"], float)
    assert isinstance(pct["p75"], float)
    assert isinstance(pct["p95"], float)
    assert isinstance(payload["risk_of_ruin"], float)
    assert isinstance(payload["goal_hit_rate"], float)
    assert isinstance(payload["mean_ending"], float)
    assert isinstance(payload["median_ending"], float)
    assert isinstance(payload["stdev_ending"], float)
    assert isinstance(payload["mean_rolls"], float)


def test_result_is_frozen_dataclass() -> None:
    result = run_monte_carlo(lambda: PassLineStrategy(unit=10), _normal_config(), 10, seed=8)
    assert isinstance(result, MonteCarloResult)
    with pytest.raises(AttributeError):
        result.n_sessions = 99  # type: ignore[misc]
