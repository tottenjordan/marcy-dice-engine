"""Pure, I/O-free view-model between the Textual app and the craps engine.

This module is the thin, testable seam the (future) TUI sits on top of. It does
three jobs, all without any printing, file access, or ``textual`` import:

1. **Parse** one human-typed bet string into a validated :class:`BetSpec`
   (:func:`parse_bet_spec`). Parsing is kept SEPARATE from engine-Bet
   construction so each half is independently testable.
2. **Build** an engine :class:`~craps_engine.portfolio.PortfolioAnalyzer` from a
   set of specs (:func:`build_portfolio_from_specs`) and a
   :class:`~craps_engine.state.GameState` for a phase (:func:`build_state`).
3. **Format** a serialized :class:`~craps_engine.portfolio.PortfolioReport` into
   the human-readable text the app renders (:func:`format_report`).

Purity contract: every function here is deterministic and side-effect free.
Displaying the returned strings is the app layer's job, never this module's.
The dependency direction is strictly ``craps_tui -> craps_engine`` (one-way), so
all engine imports live at module top-level.

Bet grammar (case-insensitive, surrounding/internal whitespace tolerant)
------------------------------------------------------------------------
Each spec is one bet on one line::

    pass:AMT            pass line
    dontpass:AMT        don't pass
    come:AMT            come (bare, still travelling)
    dontcome:AMT        don't come (bare)
    place N:AMT         place bet on box N
    take N:AMT          take odds backing point N
    lay N:AMT           lay odds backing point N

``AMT`` is a positive integer (whole dollars). ``N`` is a point/box number in
{4, 5, 6, 8, 9, 10} and is REQUIRED for ``place``/``take``/``lay`` and
FORBIDDEN for the line/come bets. The accepted separators are: a colon ``:``
before the amount, and (for the numbered bets) a space before the number, e.g.
``place 6:6``. Whitespace around each token is ignored, so ``PLACE  8 : 6`` is
also accepted.
"""

from __future__ import annotations

from fractions import Fraction
from typing import TYPE_CHECKING

from craps_engine.portfolio import PortfolioAnalyzer
from craps_engine.specs import BetSpec, build_bet, parse_bet_spec
from craps_engine.state import GameState

if TYPE_CHECKING:
    from collections.abc import Iterable

    from craps_engine.bets.base import Bet
    from craps_engine.money import FractionPayload
    from craps_engine.portfolio import PortfolioReport

#: Re-exported from :mod:`craps_engine.specs` (the single source of truth for the
#: bet grammar) so existing view-model consumers keep importing them from here.
__all__ = [
    "BetSpec",
    "build_bet",
    "build_portfolio_from_specs",
    "build_state",
    "format_report",
    "parse_bet_spec",
]

# The valid craps point / box numbers a point may take.
_VALID_NUMBERS = frozenset({4, 5, 6, 8, 9, 10})

# The totals (2..12, in table order) the matrix row renders.
_TOTALS = range(2, 13)


def build_state(point: int | None) -> GameState:
    """Build a :class:`GameState` for the requested phase.

    ``None`` yields a fresh come-out state; an ``int`` in {4,5,6,8,9,10} yields a
    state advanced to the POINT phase on that number. Any other ``int`` (e.g. a
    natural like 7) raises :class:`ValueError`, since it cannot be a point.
    """
    state = GameState()
    if point is None:
        return state
    if point not in _VALID_NUMBERS:
        msg = f"{point} is not a valid point (4,5,6,8,9,10)"
        raise ValueError(msg)
    state.apply(point)
    return state


def build_portfolio_from_specs(specs: Iterable[BetSpec]) -> PortfolioAnalyzer:
    """Map each :class:`BetSpec` to an engine :class:`Bet` and bundle them.

    Stable, unique ids are generated per bet (``f"{kind}{index}"``) so the
    portfolio composition round-trips deterministically. Place bets keep the
    engine default ``working=False`` (OFF on the come-out, matching real table
    convention); during the POINT phase a place bet is live regardless of that
    flag, which is the phase the analyzer is normally read in. Odds/come/line
    bets use their own constructor defaults.
    """
    bets: list[Bet] = [build_bet(spec, f"{spec.kind}{index}") for index, spec in enumerate(specs)]
    return PortfolioAnalyzer(bets)


def _fraction_from_payload(payload: FractionPayload) -> Fraction:
    """Reconstruct the exact :class:`Fraction` from a serialized payload.

    The lossless ``exact`` string is ``"numerator/denominator"`` (see
    :func:`craps_engine.money.serialize_fraction`), so we rebuild the value
    without ever touching the lossy float view.
    """
    num, _, denom = payload["exact"].partition("/")
    return Fraction(int(num), int(denom))


def _signed_fraction(payload: FractionPayload) -> str:
    """Render a payload Fraction with an explicit leading sign.

    Mirrors the idiom in ``examples/hedged_dp_place68.py``: :class:`Fraction`
    has no ``:+`` format spec, so the sign is built by hand from the magnitude.
    Whole-dollar values (denominator 1) render as plain ints; fractional values
    render as ``num/den``. Zero renders as ``"0"`` (no sign).
    """
    value = _fraction_from_payload(payload)
    magnitude = abs(value)
    body = magnitude.numerator if magnitude.denominator == 1 else magnitude
    if value < 0:
        return f"-{body}"
    if value > 0:
        return f"+{body}"
    return "0"


def _format_matrix_row(matrix: dict[int, FractionPayload]) -> str:
    """Render the per-total net deltas as a compact signed one-liner.

    Every total 2..12 is shown in table order (zeros render as ``5:0``) so the
    output reads like a stable calculator grid rather than a sparse list.
    """
    parts = [f"{total}:{_signed_fraction(matrix[total])}" for total in _TOTALS]
    return "  ".join(parts)


def format_report(report: PortfolioReport) -> str:
    """Render a :class:`PortfolioReport` as human-readable text for the app.

    The output is three labelled lines:

    * ``Matrix:`` the per-total net deltas (2..12, signed, zeros shown).
    * ``Lens A (single-roll EV):`` the next-roll EV, signed (e.g. ``+7/9``).
    * ``Lens B (house drag):`` the long-run expected COST, unsigned (it is a
      cost by sign convention, so no leading ``+`` is added).

    Deterministic and pure: the same report always renders the same string.
    """
    matrix_line = _format_matrix_row(report["matrix"])
    lens_a = _signed_fraction(report["single_roll_ev"])
    # House drag is a cost (positive = expected loss); render its bare magnitude.
    drag = _fraction_from_payload(report["house_drag"])
    drag_body = drag.numerator if drag.denominator == 1 else drag
    return (
        f"Matrix: {matrix_line}\n"
        f"Lens A (single-roll EV): {lens_a}\n"
        f"Lens B (house drag): {drag_body}"
    )
