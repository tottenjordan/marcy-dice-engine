"""Headless math self-check ("golden-verify") for the craps engine.

This module is the pure, I/O-free heart of the TUI's "verify the math" feature.
It recomputes a small set of canonical craps scenarios through the real engine
(:class:`~craps_engine.portfolio.PortfolioAnalyzer` +
:class:`~craps_engine.state.GameState`) and compares each result against an
exact-:class:`~fractions.Fraction` oracle that was independently hand-derived
from the dice combinatorics.

Design constraints (deliberately strict):

* **No I/O.** Nothing here prints, reads files, or touches the terminal -- it
  returns structured :class:`CheckResult` data the caller renders. Display is a
  separate layer's job.
* **Engine-only imports.** It depends solely on :mod:`craps_engine` and the
  standard library, so it can serve as a trustworthy oracle independent of any
  UI framework.
* **Exact math.** Every comparison is between exact :class:`~fractions.Fraction`
  values; the string forms on :class:`CheckResult` are purely for display.

The scenarios pinned in :data:`GOLDEN_SCENARIOS` are the canonical hedge
(Don't Pass + Place 6/8, point 4) plus two simpler, independently verifiable
cases (a lone Pass Line on the come-out and a lone Place 6 during a point) so
that drift in the engine's arithmetic is caught here.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from fractions import Fraction

from craps_engine.bets.line import DontPass, PassLine
from craps_engine.bets.place import PlaceBet
from craps_engine.portfolio import PortfolioAnalyzer
from craps_engine.state import GameState


@dataclass(frozen=True)
class CheckResult:
    """One recomputed quantity compared against its exact oracle.

    ``expected`` and ``actual`` are the ``str`` forms of the underlying
    :class:`~fractions.Fraction` values (e.g. ``"7/9"``) so the result is
    directly display-ready. ``passed`` is computed by the caller from the EXACT
    Fraction comparison, never from the strings, so normalization can never
    silently flip a verdict.
    """

    #: Human-readable identifier, e.g. ``"hedge | Lens A (single-roll EV)"``.
    label: str
    #: Display string of the hand-derived oracle Fraction.
    expected: str
    #: Display string of the engine-recomputed Fraction.
    actual: str
    #: True iff the exact oracle and the exact recomputed value are equal.
    passed: bool


# A builder returns a fresh PortfolioAnalyzer; a state builder returns the
# GameState the portfolio is evaluated against (a fresh come-out, or one advanced
# to a point).
PortfolioBuilder = Callable[[], PortfolioAnalyzer]
StateBuilder = Callable[[], GameState]


@dataclass(frozen=True)
class GoldenScenario:
    """A named scenario plus its exact oracles for a self-check pass.

    ``build_portfolio`` and ``build_state`` are pure factories (re-invoked per
    run so no state leaks between checks). ``expected_matrix`` pins only the
    totals worth asserting on for this scenario; ``expected_lens_a`` and
    ``expected_lens_b`` pin the two EV lenses. Every value is an exact
    :class:`~fractions.Fraction`.
    """

    #: Short scenario name used as the prefix of every emitted check label.
    name: str
    #: Factory for the portfolio under test.
    build_portfolio: PortfolioBuilder
    #: Factory for the table state the portfolio is evaluated against.
    build_state: StateBuilder
    #: Total -> exact net-delta oracle, for the totals this scenario pins.
    expected_matrix: dict[int, Fraction] = field(default_factory=dict)
    #: Exact Lens A (single-roll EV) oracle.
    expected_lens_a: Fraction = Fraction(0)
    #: Exact Lens B (house drag) oracle.
    expected_lens_b: Fraction = Fraction(0)


# The point the canonical hedge example sits on (matches examples/).
_HEDGE_POINT = 4
# The point used for the lone-place-6 scenario (any point works; the place bet
# is live throughout the POINT phase regardless of the specific point number).
_PLACE_POINT = 4


def _build_hedge_portfolio() -> PortfolioAnalyzer:
    """The canonical hedge: Don't Pass 10 + Place 6 (6) + Place 8 (6)."""
    dont_pass: DontPass = DontPass("dp", Fraction(10))
    return PortfolioAnalyzer(
        [
            dont_pass,
            PlaceBet("p6", 6, Fraction(6), working=True),
            PlaceBet("p8", 8, Fraction(6), working=True),
        ],
    )


def _build_point_state(point: int) -> GameState:
    """A :class:`GameState` advanced to the POINT phase on ``point``."""
    state = GameState()
    state.apply(point)
    return state


def _build_pass_line_portfolio() -> PortfolioAnalyzer:
    """A lone Pass Line of 10 (evaluated on the come-out)."""
    return PortfolioAnalyzer([PassLine("pl", Fraction(10))])


def _build_place_6_portfolio() -> PortfolioAnalyzer:
    """A lone Place 6 of 6 (evaluated during a point, where it is live)."""
    return PortfolioAnalyzer([PlaceBet("p6", 6, Fraction(6), working=True)])


#: The pinned scenarios. Each oracle Fraction is hand-derived; the derivations
#: live in tests/test_golden.py alongside the asserts.
GOLDEN_SCENARIOS: tuple[GoldenScenario, ...] = (
    # Canonical hedge: DP 10 + Place 6/8 of 6, point 4. The values the whole
    # engine illustrates (see portfolio.py / examples/hedged_dp_place68.py).
    GoldenScenario(
        name="hedge",
        build_portfolio=_build_hedge_portfolio,
        build_state=lambda: _build_point_state(_HEDGE_POINT),
        expected_matrix={
            4: Fraction(-10),  # DP loses on the point made.
            5: Fraction(0),  # nothing acts on a 5 here.
            6: Fraction(7),  # Place 6 pays 7:6 on a $6 stake.
            7: Fraction(-2),  # DP wins +10, both place bets lose -6 each.
            8: Fraction(7),  # Place 8 pays 7:6 on a $6 stake.
        },
        expected_lens_a=Fraction(7, 9),
        expected_lens_b=Fraction(7, 22),
    ),
    # Lone Pass Line 10 on the COME-OUT: 7/11 win, 2/3/12 lose, points idle.
    GoldenScenario(
        name="pass-line",
        build_portfolio=_build_pass_line_portfolio,
        build_state=GameState,  # fresh come-out, no point.
        expected_matrix={
            2: Fraction(-10),  # come-out craps.
            4: Fraction(0),  # point number: NO_ACTION on the come-out.
            7: Fraction(10),  # come-out natural pays 1:1.
        },
        expected_lens_a=Fraction(10, 9),
        expected_lens_b=Fraction(14, 99),
    ),
    # Lone Place 6 of 6 during a point: 6 wins 7:6, 7 sweeps the stake.
    GoldenScenario(
        name="place-6",
        build_portfolio=_build_place_6_portfolio,
        build_state=lambda: _build_point_state(_PLACE_POINT),
        expected_matrix={
            5: Fraction(0),  # untouched total.
            6: Fraction(7),  # the placed number hits at 7:6.
            7: Fraction(-6),  # seven-out sweeps the $6 stake.
        },
        expected_lens_a=Fraction(-1, 36),
        expected_lens_b=Fraction(1, 11),
    ),
)


def _check(label: str, expected: Fraction, actual: Fraction) -> CheckResult:
    """Build a :class:`CheckResult`, comparing the EXACT Fractions for ``passed``."""
    return CheckResult(
        label=label,
        expected=str(expected),
        actual=str(actual),
        passed=expected == actual,
    )


def run_golden_checks() -> list[CheckResult]:
    """Recompute every golden scenario and compare against its exact oracles.

    For each scenario this instantiates a fresh portfolio + state, recomputes the
    pinned matrix totals plus both EV lenses through the engine, and emits one
    :class:`CheckResult` per checked quantity. ``passed`` is the exact-Fraction
    equality of oracle vs. recomputed value, so any drift in the engine's math
    surfaces as a failed result.
    """
    results: list[CheckResult] = []
    for scenario in GOLDEN_SCENARIOS:
        portfolio = scenario.build_portfolio()
        state = scenario.build_state()

        matrix = portfolio.net_payout_matrix(state)
        for total, expected_delta in scenario.expected_matrix.items():
            results.append(
                _check(f"{scenario.name} | matrix[{total}]", expected_delta, matrix[total]),
            )

        results.append(
            _check(
                f"{scenario.name} | Lens A (single-roll EV)",
                scenario.expected_lens_a,
                portfolio.single_roll_ev(state),
            ),
        )
        results.append(
            _check(
                f"{scenario.name} | Lens B (house drag)",
                scenario.expected_lens_b,
                portfolio.house_drag(),
            ),
        )
    return results
