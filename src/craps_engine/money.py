"""Exact-arithmetic money & odds helpers, plus UI/MC-ready serialization.

This module is the single boundary where exact :class:`~fractions.Fraction`
values are turned into display-friendly floats/strings. Everything inside the
engine stays in exact arithmetic; only :func:`serialize_fraction` (and the
``float`` views below) cross over into lossy float-land, and only for display.
"""

from __future__ import annotations

from dataclasses import dataclass
from fractions import Fraction


@dataclass(frozen=True)
class RatioOdds:
    """Win:stake ratio, e.g. 7:6 means a stake of 6 wins 7.

    Frozen so odds values are hashable and safe to share. The two ints are the
    win and stake legs of a payout ratio exactly as quoted at a craps table
    (e.g. Place 6 pays ``7:6``).
    """

    win: int
    stake: int

    def as_fraction(self) -> Fraction:
        """Return the ratio as an exact ``win/stake`` Fraction."""
        return Fraction(self.win, self.stake)

    def payout(self, stake: Fraction) -> Fraction:
        """Net winnings (excludes the returned stake) for a given stake.

        Multiplying by the exact ratio keeps the result exact, so a 7:6 bet on
        a stake of 6 returns exactly 7 with no float drift.
        """
        return stake * self.as_fraction()

    def to_dict(self) -> dict[str, object]:
        """Serialize to a UI/MC-friendly shape.

        ``ratio`` is the canonical ``win:stake`` string; ``float`` is a lossy
        convenience view for display/analytics only.
        """
        return {"ratio": f"{self.win}:{self.stake}", "float": float(self.as_fraction())}


def serialize_fraction(value: Fraction, *, as_percent: bool = True) -> dict[str, object]:
    """Exact + float + display payload for one Fraction.

    The UI shows ``display`` while analytics/Monte-Carlo layers consume the
    exact ``exact`` string or the lossy ``float``. ``display`` is rendered as a
    3-dp percentage by default, or a 4-dp plain decimal when
    ``as_percent=False``.
    """
    # The only place floats are intentionally introduced, and strictly for
    # human-readable display.
    display = f"{float(value) * 100:.3f}%" if as_percent else f"{float(value):.4f}"
    return {
        # Keep numerator/denominator explicit so the exact value round-trips.
        "exact": f"{value.numerator}/{value.denominator}",
        "float": float(value),
        "display": display,
    }
