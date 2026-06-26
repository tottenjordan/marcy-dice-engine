"""Exact-arithmetic money & odds helpers, plus UI/MC-ready serialization.

This module is the single boundary where exact :class:`~fractions.Fraction`
values are turned into display-friendly floats/strings. Everything inside the
engine stays in exact arithmetic; only :func:`serialize_fraction` (and the
``float`` views below) cross over into lossy float-land, and only for display.
"""

from __future__ import annotations

from dataclasses import dataclass
from fractions import Fraction
from typing import TypedDict


class RatioPayload(TypedDict):
    """Serialized shape of a :class:`RatioOdds` value.

    ``ratio`` is the canonical ``win:stake`` string; ``float`` is a lossy
    convenience view for display/analytics only.
    """

    ratio: str
    float: float


class FractionPayload(TypedDict):
    """Serialized shape of a single Fraction.

    ``exact`` round-trips the value losslessly; ``float`` and ``display`` are
    lossy views meant only for analytics convenience and human display.
    """

    exact: str
    float: float
    display: str


@dataclass(frozen=True)
class RatioOdds:
    """Win:stake ratio, e.g. 7:6 means a stake of 6 wins 7.

    Frozen so odds values are hashable and safe to share. The two ints are the
    win and stake legs of a payout ratio exactly as quoted at a craps table
    (e.g. Place 6 pays ``7:6``).
    """

    win: int
    stake: int

    def __post_init__(self) -> None:
        """Fail fast on invalid odds instead of deferring a ZeroDivisionError.

        A non-positive stake can never form a valid payout ratio, and a
        negative win is nonsensical. Raise immediately with the bad value so
        the error surfaces at construction, not at some later ``payout`` call.
        """
        if self.stake <= 0:
            msg = f"stake must be positive, got {self.stake}"
            raise ValueError(msg)
        if self.win < 0:
            msg = f"win must be non-negative, got {self.win}"
            raise ValueError(msg)

    def as_fraction(self) -> Fraction:
        """Return the ratio as an exact ``win/stake`` Fraction."""
        return Fraction(self.win, self.stake)

    def payout(self, stake: Fraction) -> Fraction:
        """Net winnings (excludes the returned stake) for a given stake.

        Multiplying by the exact ratio keeps the result exact, so a 7:6 bet on
        a stake of 6 returns exactly 7 with no float drift.
        """
        return stake * self.as_fraction()

    def to_dict(self) -> RatioPayload:
        """Serialize to a UI/MC-friendly shape.

        ``ratio`` is the canonical ``win:stake`` string; ``float`` is a lossy
        convenience view for display/analytics only.
        """
        return {"ratio": f"{self.win}:{self.stake}", "float": float(self.as_fraction())}


def serialize_fraction(value: Fraction, *, as_percent: bool = True) -> FractionPayload:
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
