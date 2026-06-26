"""Runnable showcase: a hedged Don't-Pass line read through TWO EV lenses.

The strategy
------------
**Don't Pass 10, hedged with Place 6 (6) and Place 8 (6), point established at
4.** This is the canonical example the whole engine was built to illustrate: a
"wrong-way" line bet whose seven-out win is hedged by two place bets that win on
the very numbers (6 and 8) that the Don't bettor fears, smoothing the
short-term swings.

What to learn from it (the two lenses tell DIFFERENT stories)
-------------------------------------------------------------
* **Lens A -- single-roll EV (current state).** Conditioned on already being on
  the point, the next roll's probability-weighted net delta is POSITIVE
  (``+7/9 ~= +0.78``). Once a point is set the Don't bettor is the statistical
  FAVORITE -- there are more ways to roll a 7 than to make any single point -- so
  the immediate outlook looks rosy.

* **Lens B -- house drag (long-run cost).** Summed over the bet's full life the
  portfolio still concedes a POSITIVE expected cost (``7/22 ~= 0.318``). That is
  the edge already paid up front (the Don't bettor paid it at the come-out, via
  the bar-12 push; the place bets pay it on every resolution).

There is no contradiction: a healthy current-state number and a real long-run
cost coexist. A tool that reported only one would lie by omission. The lesson:
hedging lowers short-term VARIANCE but stacks multiple house edges, so BOTH
lenses must be read together.

This module is under ``examples/`` (not ``src/``), so printing is allowed here
and ONLY here. ``build_portfolio`` / ``build_state`` / ``build_report`` are PURE
(no I/O); every ``print`` lives inside ``main`` (and the pure display helpers it
calls), keeping the engine's no-IO contract intact.
"""

from __future__ import annotations

from fractions import Fraction

from craps_engine.bets.line import DontPass
from craps_engine.bets.place import PlaceBet
from craps_engine.money import FractionPayload, serialize_fraction
from craps_engine.portfolio import PortfolioAnalyzer, PortfolioReport
from craps_engine.state import GameState

# The point the table is on for this worked example.
_POINT = 4

# The totals, in table order, used to render the net-payout matrix row.
_TOTALS = range(2, 13)


def build_portfolio() -> PortfolioAnalyzer:
    """Return the hedged showcase portfolio (DP 10 + Place 6/8 of 6 each).

    The two place bets are explicitly ``working=True`` so the demo reads clearly,
    though during the POINT phase place bets are live regardless of that flag.
    """
    return PortfolioAnalyzer(
        [
            DontPass("dp", Fraction(10)),
            PlaceBet("p6", 6, Fraction(6), working=True),
            PlaceBet("p8", 8, Fraction(6), working=True),
        ],
    )


def build_state() -> GameState:
    """Return a :class:`GameState` advanced to POINT with the point set to 4."""
    state = GameState()
    state.apply(_POINT)
    return state


def build_report() -> PortfolioReport:
    """PURE: build portfolio + state and return the analyzer's serialized report.

    This is the structured data the integration test asserts against, so it must
    stay free of any printing or other I/O.
    """
    return build_portfolio().report(build_state())


def _format_matrix_row(matrix: dict[int, FractionPayload]) -> str:
    """Render the per-total net deltas as a compact, signed one-liner.

    Each total maps to a serialized Fraction payload; we read its lossless
    ``exact`` string, turn it back into a Fraction, and print it with an explicit
    sign so wins (+) and losses (-) are obvious at a glance.
    """
    parts: list[str] = []
    for total in _TOTALS:
        payload = matrix[total]
        # Reconstruct the exact value for display from the lossless payload.
        num, denom = payload["exact"].split("/")
        value = Fraction(int(num), int(denom))
        # Fraction has no "+" presentation spec, so build the signed token by
        # hand from the magnitude. Whole-dollar deltas (denominator 1) read as
        # plain ints; the sign is prefixed explicitly.
        magnitude = abs(value)
        token = magnitude.numerator if magnitude.denominator == 1 else magnitude
        sign = "-" if value < 0 else "+"
        parts.append(f"{total}: {sign}{token}")
    return ", ".join(parts)


def main() -> None:
    """Print a heavily commented, human-readable breakdown of the hedge.

    All printing is confined here. The numbers come straight from the pure
    :func:`build_report`, so what is printed is exactly what the test verifies.
    """
    report = build_report()

    print("=" * 72)
    print("Hedged strategy: Don't Pass 10 + Place 6 (6) + Place 8 (6), point = 4")
    print("=" * 72)
    print()

    # --- The per-total net-payout matrix -----------------------------------
    # For each possible next total (2..12) this is the net bankroll change if
    # that total were rolled right now. Key reads: 7 wins the Don't (+10) but
    # sweeps both place bets (-6, -6) for a net -2; the point 4 losing the Don't
    # is -10; a 6 or 8 pays a place bet 7:6 on 6 -> +7.
    print("Per-total net payout (next roll, point 4):")
    print("  " + _format_matrix_row(report["matrix"]))
    print()

    # --- Lens A: single-roll EV (current-state / variance view) ------------
    ev = report["single_roll_ev"]
    print("Lens A -- single-roll EV (current state):")
    print(f"  exact = {ev['exact']}   (~ {ev['float']:+.4f})")
    print("  POSITIVE: once the point is established the Don't-Pass bettor is the")
    print("  favorite (more ways to roll a 7 than to make the point), so the very")
    print("  next roll looks good. This is the short-horizon, variance-flavored view.")
    print()

    # --- Lens B: house drag (long-run cost view) ---------------------------
    drag = report["house_drag"]
    # serialize_fraction also gives us the percentage display when wanted.
    drag_pct = serialize_fraction(Fraction(7, 22), as_percent=True)["display"]
    print("Lens B -- house drag (long-run cost):")
    print(f"  exact = {drag['exact']}   (~ {drag['float']:.4f}  =  {drag_pct})")
    print("  POSITIVE COST: the honest long-run expected loss. This is the edge")
    print("  already conceded -- the Don't paid it at the come-out (bar-12 push),")
    print("  the place bets pay it on every resolution. It does NOT depend on phase.")
    print()

    # --- The lesson --------------------------------------------------------
    print("Lesson: hedging lowers short-term VARIANCE but STACKS house edges.")
    print("Lens A (current state) and Lens B (long run) tell different stories;")
    print("both must be read -- a healthy next-roll EV does not erase the built-in cost.")
    print("=" * 72)


if __name__ == "__main__":
    main()
