"""Integration test keeping the Monte Carlo strategy-comparison demo honest.

The :mod:`examples.simulate_strategies` module races three strategies through the
SAME deterministic Monte Carlo batch (fixed seed + shared config + n_sessions).
This test imports the module's PURE :func:`build_results` and asserts the
structured aggregate stats: that the batch is reproducible (same seed -> equal
results), that a pinned regression oracle value still holds (guarding against
drift), and basic sanity bounds. It deliberately asserts ONLY the structured
data, never the printed text formatting. A single call to ``main()`` is exercised
via ``capsys`` purely to guard against runtime errors in the rendered table.

``build_results`` runs a real Monte Carlo batch, so the oracle / labels / sanity
tests SHARE one module-scoped run via the ``results`` fixture; only the
reproducibility test (which must prove determinism with two independent calls)
and ``main()`` run their own batches, keeping the file to ~4 batches total.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from examples.simulate_strategies import _N_SESSIONS, build_results, main

if TYPE_CHECKING:
    from craps_engine.montecarlo import MonteCarloResult

# The full set of strategy labels the demo must report.
_EXPECTED_LABELS = {"Pass Line", "Pass + Odds", "DP + Place 6/8"}

# Pinned regression oracle: with the fixed seed/config/n_sessions, "Pass + Odds"
# busts in exactly 3.5% of sessions and ends with this exact mean bankroll.
# Floats are deterministic given the seed, so any drift in the engine or scenario
# trips these. Captured from a single observed run at _N_SESSIONS == 200.
_ORACLE_LABEL = "Pass + Odds"
_ORACLE_ROR = 0.035
_ORACLE_MEAN_ENDING = 289.655


@pytest.fixture(scope="module")
def results() -> dict[str, MonteCarloResult]:
    """One shared Monte Carlo batch reused across the read-only assertions."""
    return build_results()


def test_build_results_is_reproducible() -> None:
    # Same seed -> identical MonteCarloResults (frozen dataclass, == works).
    # Two INDEPENDENT calls (not the shared fixture) to prove determinism.
    assert build_results() == build_results()


def test_build_results_pinned_oracle(results: dict[str, MonteCarloResult]) -> None:
    result = results[_ORACLE_LABEL]
    assert result.risk_of_ruin == _ORACLE_ROR
    assert result.mean_ending == _ORACLE_MEAN_ENDING


def test_build_results_has_expected_labels(
    results: dict[str, MonteCarloResult],
) -> None:
    assert set(results) == _EXPECTED_LABELS


def test_build_results_sanity_bounds(results: dict[str, MonteCarloResult]) -> None:
    for result in results.values():
        assert result.n_sessions == _N_SESSIONS
        assert 0.0 <= result.risk_of_ruin <= 1.0
        assert 0.0 <= result.goal_hit_rate <= 1.0


def test_main_runs_and_prints(capsys: pytest.CaptureFixture[str]) -> None:
    # Smoke-test the demo end to end: it must run without raising and emit text.
    main()
    captured = capsys.readouterr()
    assert captured.out.strip()
