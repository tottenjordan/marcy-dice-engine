"""Immutable rules-variant value object carried on ``GameState`` + ``SessionConfig``.

A :class:`Ruleset` captures the come-out spine that distinguishes craps variants:
which totals are naturals, which are craps, which establish a point (and are
therefore placeable / oddsable), and whether the Don't side is offered. Bets read
the ruleset off ``state`` during ``resolve`` and the :class:`~craps_engine.play.PlayController`
enforces per-ruleset placement legality — no bet signatures change.

This module is pure data with no dependency on other engine modules, so
``state.py`` may import it without a cycle.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Ruleset:
    """A frozen, hashable craps rules variant.

    Attributes:
        name: Short identifier (e.g. ``"standard"``, ``"crapless"``).
        point_numbers: Totals that establish the point on the come-out — also the
            valid come-points and the placeable / oddsable box numbers.
        pass_naturals: Come-out totals on which the Pass line wins immediately.
        pass_craps: Come-out totals on which the Pass line loses immediately.
        allow_dont: Whether Don't-side bets (Don't Pass / Don't Come / Lay) are
            offered under this variant.
    """

    name: str
    point_numbers: frozenset[int]
    pass_naturals: frozenset[int]
    pass_craps: frozenset[int]
    allow_dont: bool


#: Ordinary craps: points 4-10, 7/11 win, 2/3/12 craps, Don't side offered.
STANDARD = Ruleset(
    name="standard",
    point_numbers=frozenset({4, 5, 6, 8, 9, 10}),
    pass_naturals=frozenset({7, 11}),
    pass_craps=frozenset({2, 3, 12}),
    allow_dont=True,
)

#: Crapless ("Never Ever Craps"): only 7 is a natural, every other total becomes a
#: point (2, 3, 11, 12 included), nothing craps out, and the Don't side is not offered.
CRAPLESS = Ruleset(
    name="crapless",
    point_numbers=frozenset({2, 3, 4, 5, 6, 8, 9, 10, 11, 12}),
    pass_naturals=frozenset({7}),
    pass_craps=frozenset(),
    allow_dont=False,
)
