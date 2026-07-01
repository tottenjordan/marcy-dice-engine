"""Central exact odds / payout / house-edge table -- the engine's math core.

Every number in this module is an exact :class:`~fractions.Fraction` taken from
the canonical craps math reference in CODE_STANDARDS.md. Each value carries a
comment explaining WHERE it comes from so a future reader can trust it without
re-deriving the combinatorics. No floats live here: floats only ever appear at
the display boundary via :func:`craps_engine.money.serialize_fraction`.

Two complementary "lenses" on house edge are stored per place bet:

* ``house_edge`` -- the edge *per resolution* (per bet that wins or loses).
* ``house_edge_per_roll`` -- the edge *per dice roll*, which scales the
  per-resolution edge by the probability that the bet resolves on any given
  roll. The portfolio analyzer uses both to compare bets fairly.
"""

from __future__ import annotations

from dataclasses import dataclass
from fractions import Fraction
from typing import TypedDict

from craps_engine.money import FractionPayload, RatioOdds, RatioPayload, serialize_fraction

# ---------------------------------------------------------------------------
# Dice-total probabilities (the foundation every other number rests on).
# ---------------------------------------------------------------------------
# Two six-sided dice yield 36 equally likely ordered outcomes. The number of
# ordered combinations producing each total is the classic craps distribution:
#   2:1  3:2  4:3  5:4  6:5  7:6  8:5  9:4  10:3  11:2  12:1
# Each probability is exactly ways/36.
_WAYS_BY_TOTAL: dict[int, int] = {
    2: 1,
    3: 2,
    4: 3,
    5: 4,
    6: 5,
    7: 6,
    8: 5,
    9: 4,
    10: 3,
    11: 2,
    12: 1,
}

#: Total (2..12) -> exact probability as ``Fraction(ways, 36)``. Reused by the
#: portfolio analyzer. Sums to exactly 1 (36/36).
TOTAL_PROBABILITY: dict[int, Fraction] = {
    total: Fraction(ways, 36) for total, ways in _WAYS_BY_TOTAL.items()
}

# The numbers a shooter can establish/place. 7 and 11 are NOT point/place
# numbers; the craps numbers 2, 3, 12 are not either.
_VALID_PLACE_NUMBERS: frozenset[int] = frozenset({4, 5, 6, 8, 9, 10})


class BetSpecPayload(TypedDict):
    """Serialized shape of a :class:`BetSpec`.

    ``house_edge_per_roll`` is ``None`` for bets (e.g. line bets) that have no
    meaningful per-roll edge; otherwise it carries the same serialized Fraction
    shape as ``house_edge`` so a UI / Monte-Carlo layer consumes one form.
    """

    key: str
    payout: RatioPayload
    house_edge: FractionPayload
    house_edge_per_roll: FractionPayload | None


@dataclass(frozen=True)
class BetSpec:
    """Immutable description of one bet's exact economics.

    Frozen so specs are hashable and safe to share from the module-level tables
    below. ``house_edge`` is the per-resolution edge; ``house_edge_per_roll`` is
    the per-roll edge (``None`` when the concept does not apply, e.g. line bets
    whose resolution timing is not a simple single-number race against the 7).
    """

    key: str
    payout: RatioOdds
    house_edge: Fraction
    house_edge_per_roll: Fraction | None

    def to_dict(self) -> BetSpecPayload:
        """Serialize to a UI/MC-friendly shape.

        Edge fields use :func:`serialize_fraction` (exact + float + display);
        ``payout`` delegates to :meth:`RatioOdds.to_dict`. ``house_edge_per_roll``
        stays ``None`` when unset rather than being coerced to a zero Fraction,
        so consumers can distinguish "no per-roll edge" from "zero edge".
        """
        return {
            "key": self.key,
            "payout": self.payout.to_dict(),
            "house_edge": serialize_fraction(self.house_edge),
            "house_edge_per_roll": (
                None
                if self.house_edge_per_roll is None
                else serialize_fraction(self.house_edge_per_roll)
            ),
        }


# ---------------------------------------------------------------------------
# Line bets: Pass Line and Don't Pass.
# ---------------------------------------------------------------------------
# Pass Line edge = 7/495 (~1.414%). Derivation: P(win) = 244/495 and
# P(lose) = 251/495 over the full come-out + point resolution tree, so the
# edge is (251 - 244)/495 = 7/495.
#
# Don't Pass (bar 12) edge = 3/220 (~1.364%). With the 12 barred on the come
# out, P(win) = 949/1980, P(lose) = 976/1980, and the remaining mass is the
# barred push; the edge works out to 27/1980 = 3/220.
#
# Both pay even money (1:1). house_edge_per_roll is None: a line bet's life
# spans an entire come-out-to-resolution sequence, not a single number's race
# against the 7, so a per-roll edge is not the right lens for it.
REGISTRY: dict[str, BetSpec] = {
    "pass_line": BetSpec(
        key="pass_line",
        payout=RatioOdds(1, 1),
        house_edge=Fraction(7, 495),
        house_edge_per_roll=None,
    ),
    "dont_pass": BetSpec(
        key="dont_pass",
        payout=RatioOdds(1, 1),
        house_edge=Fraction(3, 220),
        house_edge_per_roll=None,
    ),
}


# ---------------------------------------------------------------------------
# Place bets: per-resolution and per-roll edges.
# ---------------------------------------------------------------------------
# Per-resolution house edge comes from paying LESS than the true odds:
#   Place 6/8 pays 7:6 (true 6:5)  -> edge 1/66  (~1.515%)
#   Place 5/9 pays 7:5 (true 3:2)  -> edge 1/25  (4.000%)
#   Place 4/10 pays 9:5 (true 2:1) -> edge 1/15  (~6.667%)
#
# Per-roll edge = per-resolution edge x P(bet resolves this roll). A place bet
# resolves only when the number or a 7 appears; otherwise the dice are
# irrelevant to it. Ways-to-resolve = ways(number) + ways(7):
#   6/8:  5 + 6 = 11  -> P(resolve) = 11/36
#   5/9:  4 + 6 = 10  -> P(resolve) = 10/36
#   4/10: 3 + 6 =  9  -> P(resolve) =  9/36
#
# Payout ratios and edges are mirror-symmetric across the 6/8, 5/9, 4/10 pairs
# because each pair has identical odds and dice combinatorics.
_PLACE_PAYOUT: dict[int, RatioOdds] = {
    6: RatioOdds(7, 6),
    8: RatioOdds(7, 6),
    5: RatioOdds(7, 5),
    9: RatioOdds(7, 5),
    4: RatioOdds(9, 5),
    10: RatioOdds(9, 5),
}

_PLACE_EDGE: dict[int, Fraction] = {
    6: Fraction(1, 66),
    8: Fraction(1, 66),
    5: Fraction(1, 25),
    9: Fraction(1, 25),
    4: Fraction(1, 15),
    10: Fraction(1, 15),
}


def _ways_to_resolve(number: int) -> int:
    """Ways a place bet on ``number`` resolves on a single roll.

    A place bet is decided only by its own number (win) or a 7 (lose); every
    other total leaves it standing. So the resolving combinations are
    ``ways(number) + ways(7)``.
    """
    return _WAYS_BY_TOTAL[number] + _WAYS_BY_TOTAL[7]


#: Place number -> its :class:`BetSpec`, with exact per-resolution AND per-roll
#: edges. Built from the payout/edge tables above so the two stay in lockstep.
PLACE_SPECS: dict[int, BetSpec] = {
    number: BetSpec(
        key=f"place_{number}",
        payout=_PLACE_PAYOUT[number],
        house_edge=_PLACE_EDGE[number],
        # Per-roll edge scales the per-resolution edge by P(resolve this roll).
        house_edge_per_roll=_PLACE_EDGE[number] * Fraction(_ways_to_resolve(number), 36),
    )
    for number in sorted(_VALID_PLACE_NUMBERS)
}


def place_spec(number: int) -> BetSpec:
    """Return the :class:`BetSpec` for a place number (4,5,6,8,9,10).

    Raises :class:`ValueError` for any number that cannot be placed (e.g. 7,
    11, or the craps numbers) so callers fail fast on a bad bet request.
    """
    if number not in PLACE_SPECS:
        msg = f"cannot place {number}: valid place numbers are 4, 5, 6, 8, 9, 10"
        raise ValueError(msg)
    return PLACE_SPECS[number]


def place_unit(number: int) -> int:
    """Smallest whole-dollar Place stake on ``number`` that pays whole dollars.

    A Place bet pays at a win:stake ratio (see ``_PLACE_PAYOUT``), so a wager of
    ``stake`` dollars returns ``stake * (win / stake) = win`` dollars -- an
    integer -- only when the wager is a multiple of the ratio's *stake leg*.
    Any smaller or non-multiple wager pushes the payout off a whole-dollar
    boundary and the casino rounds it down, quietly worsening the bettor's
    already-negative edge. The stake leg is therefore the optimal advisory unit:
    the smallest stake for which ``stake x (win/stake)`` is exact, and every
    whole-dollar multiple of it stays exact too. Returning it lets the UI nudge
    players onto efficient stakes (e.g. $6 on the 6, not $5).

    Concrete table (number -> unit, from the payout ratio):

    * 6 / 8  -> 6  (pays 7:6)
    * 5 / 9  -> 5  (pays 7:5)
    * 4 / 10 -> 5  (pays 9:5)

    Delegates validation to :func:`place_spec`, so non-place numbers (7, 11, the
    craps numbers) raise :class:`ValueError` and this helper fails fast too.
    """
    return place_spec(number).payout.stake


def _snap_to_unit(unit: int, amount: int) -> int:
    """Round ``amount`` to the nearest whole multiple of ``unit`` (ties round up).

    Shared rounding rule behind :func:`snap_to_place_unit` and
    :func:`snap_to_odds_unit`: a target at or below one unit floors at one unit
    (so a positive stake is never silently dropped to $0), and an exact halfway
    target rounds UP to the larger multiple. ``unit`` is assumed already validated
    by the caller (both public snappers derive it from a validating helper).
    """
    if amount <= unit:
        return unit
    quotient, remainder = divmod(amount, unit)
    if remainder * 2 >= unit:  # round half up to the larger multiple
        quotient += 1
    return quotient * unit


def snap_to_place_unit(number: int, amount: int) -> int:
    """Round a Place stake on ``number`` to the nearest whole multiple of its unit.

    Given a target ``amount``, return the closest whole-dollar multiple of
    :func:`place_unit` for ``number`` -- so the wager always lands on a stake that
    pays whole dollars (e.g. on the 6/8 the stake snaps to a $6 multiple, on the
    4/5/9/10 to a $5 multiple). Ties round UP (halfway between two multiples picks
    the larger), and a positive target never snaps below one unit, so a stake is
    never silently dropped to $0.

    Examples (``number`` -> unit): ``snap_to_place_unit(6, 10) == 12`` (nearest $6
    multiple to $10), ``snap_to_place_unit(5, 10) == 10``, ``snap_to_place_unit(8,
    13) == 12``, ``snap_to_place_unit(6, 3) == 6`` (floor at one unit).

    This is a play-mode convenience for callers that want to enforce efficient
    stakes (the web felt snaps button/press amounts through it); the engine's own
    :meth:`~craps_engine.play.PlayController.place_bet` still accepts any positive
    amount. Delegates validation to :func:`place_unit`, so non-place numbers raise
    :class:`ValueError`.
    """
    return _snap_to_unit(place_unit(number), amount)


# ---------------------------------------------------------------------------
# Free Odds (true odds) ratios.
# ---------------------------------------------------------------------------
# Free Odds carry ZERO house edge: they pay the exact true odds against the
# point hitting before a 7. True odds = P(7) : P(number) reduced.
#   4/10: P(7):P(4)  = 6:3 = 2:1
#   5/9:  P(7):P(5)  = 6:4 = 3:2
#   6/8:  P(7):P(6)  = 6:5
# "Take" odds (Pass side, betting the point hits first) win at these ratios.
# "Lay" odds (Don't side, betting the 7 hits first) are the exact INVERSE,
# because the Don't bettor is the favorite and must risk more to win less:
#   4/10: 1:2   5/9: 2:3   6/8: 5:6
_TAKE_ODDS: dict[int, RatioOdds] = {
    4: RatioOdds(2, 1),
    10: RatioOdds(2, 1),
    5: RatioOdds(3, 2),
    9: RatioOdds(3, 2),
    6: RatioOdds(6, 5),
    8: RatioOdds(6, 5),
}


def odds_ratio(*, take: bool, number: int) -> RatioOdds:
    """True-odds ratio for a Free Odds bet on a point ``number``.

    ``take=True`` returns the Pass-side take odds (e.g. 4 -> 2:1).
    ``take=False`` returns the Don't-side lay odds, the exact inverse (e.g.
    4 -> 1:2). Raises :class:`ValueError` for non-point numbers.
    """
    if number not in _TAKE_ODDS:
        msg = f"not a valid point number: {number} (valid points: 4, 5, 6, 8, 9, 10)"
        raise ValueError(msg)
    take_odds = _TAKE_ODDS[number]
    if take:
        return take_odds
    # Lay odds are the inverse ratio: swap win and stake legs.
    return RatioOdds(take_odds.stake, take_odds.win)


def odds_unit(*, take: bool, number: int) -> int:
    """Smallest whole-dollar Free-Odds stake on ``number`` that pays whole dollars.

    Like :func:`place_unit`, the optimal advisory unit is the payout ratio's
    *stake leg*: a Free-Odds wager returns whole dollars only when it is a whole
    multiple of that leg (any smaller/non-multiple stake pushes the exact-true-odds
    payout off a whole-dollar boundary and the casino rounds it down). Because odds
    pay the exact true odds, ``take`` and ``lay`` have different units:

    * take (Pass side): 4/10 -> 1 (2:1), 5/9 -> 2 (3:2), 6/8 -> 5 (6:5)
    * lay  (Don't side): 4/10 -> 2 (1:2), 5/9 -> 3 (2:3), 6/8 -> 6 (5:6)

    Returning it lets the UI nudge players onto efficient odds stakes. Delegates
    validation to :func:`odds_ratio`, so non-point numbers raise :class:`ValueError`.
    """
    return odds_ratio(take=take, number=number).stake


def snap_to_odds_unit(*, take: bool, number: int, amount: int) -> int:
    """Round a Free-Odds stake to the nearest whole multiple of its unit.

    The odds counterpart of :func:`snap_to_place_unit`: snap ``amount`` to the
    closest whole-dollar multiple of :func:`odds_unit` for this ``take``/``number``
    so the true-odds payout lands in whole dollars (e.g. take odds on the 6/8 snap
    to $5 multiples, lay odds on the 6/8 to $6 multiples; take odds on the 4/10 are
    already whole for any stake, so snapping is a no-op there). Ties round UP and a
    positive stake never snaps below one unit, matching the place snapper.

    A play-mode convenience for the web felt's shared stake box; the engine's own
    :meth:`~craps_engine.play.PlayController.place_bet` still accepts any positive
    amount (subject to the 3-4-5x table maximum enforced at placement). Delegates
    validation to :func:`odds_unit`, so non-point numbers raise :class:`ValueError`.
    """
    return _snap_to_unit(odds_unit(take=take, number=number), amount)
