"""Free Odds bets: :class:`TakeOdds` (Pass side) and :class:`LayOdds` (Don't side).

Free Odds are the only bets in craps with ZERO house edge: they pay the exact
TRUE odds against the point hitting before a 7. They are *backing* bets placed
BEHIND a flat line bet once a point exists, and they bind to a specific point
``number`` (the point being backed):

* :class:`TakeOdds` backs the Pass side ("taking" odds): it wins when the point
  number is rolled before a 7, paying true odds (4/10 -> 2:1, 5/9 -> 3:2,
  6/8 -> 6:5).
* :class:`LayOdds` backs the Don't side ("laying" odds): it wins when a 7 is
  rolled before the point, paying the INVERSE true odds (4/10 -> 1:2, 5/9 ->
  2:3, 6/8 -> 5:6) -- the Don't bettor is the favorite, so they risk more to
  win less.

Both are live ONLY during :attr:`~craps_engine.state.Phase.POINT`. On the
come-out the odds are "off" (NO_ACTION), mirroring real table rules where a
player's odds are not working on the come-out unless they explicitly call them
on. The exact ratios come from :func:`craps_engine.registry.odds_ratio` rather
than being hard-coded here, so the engine has one source of truth for true odds.

MAX-ODDS POLICY (enforced at PLACEMENT, never at resolution)
------------------------------------------------------------
Real tables cap how much odds you may back relative to your flat bet (commonly
"3-4-5x": 3x behind a 4/10, 4x behind a 5/9, 5x behind a 6/8). That cap is a
TABLE-RULES concern, not a property of how an odds bet *resolves*: ``resolve``
here always settles whatever stake was placed. The multipliers live in
:data:`MAX_ODDS_MULTIPLIER`, and the interactive
:class:`~craps_engine.play.PlayController` is the validation hook that enforces
them (plus the "a flat bet must back the odds" rule) when a bet is PLACED -- see
``PlayController._reject_odds_table_rules``. Keeping enforcement at placement and
out of resolution means the static analyzer / Monte Carlo paths, which settle
pre-built bets, are unaffected.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from craps_engine.bets.base import Bet, BetPayload, Resolution, ResolutionStatus
from craps_engine.registry import odds_ratio
from craps_engine.state import Phase

if TYPE_CHECKING:
    from fractions import Fraction

    from craps_engine.dice import DiceRoll
    from craps_engine.state import GameState


class OddsBetPayload(BetPayload):
    """Serialized shape of an odds bet: the base bet payload plus its point.

    Extends :class:`~craps_engine.bets.base.BetPayload` with the bound point
    ``number`` so the wager's backed point round-trips through serialization.
    """

    number: int


# The point numbers a Free Odds bet may back. 7 and 11, and the craps numbers
# 2/3/12, are never points, so binding odds to them is rejected fail-fast.
_VALID_POINTS = frozenset({4, 5, 6, 8, 9, 10})

# The seven, named for readability at its use sites.
_SEVEN = 7

#: Common "3-4-5x" max-odds multipliers by point number, kept as DOCUMENTATION
#: only. The engine does NOT enforce these at resolution time -- validating a
#: stake against the table maximum is a table-rules / portfolio concern (a future
#: validation hook), not part of how an odds bet settles. See module docstring.
MAX_ODDS_MULTIPLIER: dict[int, int] = {
    4: 3,
    10: 3,
    5: 4,
    9: 4,
    6: 5,
    8: 5,
}


class _OddsBet(Bet):
    """Shared base for the two Free Odds bets: stores and validates ``number``.

    Both odds bets carry, beyond the base :class:`Bet` fields, the point
    ``number`` they back. This base centralizes that extra field's validation
    (it must be a real point) and serialization so the concrete subclasses only
    differ in their resolve rules.
    """

    def __init__(
        self,
        id: str,  # noqa: A002 (mirrors Bet's public ``id`` name)
        number: int,
        amount: Fraction | int,
        *,
        working: bool = True,
    ) -> None:
        """Create an odds bet bound to a point ``number``.

        Rejects any ``number`` that is not a real point (4,5,6,8,9,10) fail-fast,
        then defers stake validation/normalization to :class:`Bet`.
        """
        if number not in _VALID_POINTS:
            msg = f"not a valid point number: {number} (valid points: 4, 5, 6, 8, 9, 10)"
            raise ValueError(msg)
        super().__init__(id, amount, working=working)
        #: The point number this odds bet is backing.
        self.number = number

    def to_dict(self) -> OddsBetPayload:
        """Serialize, adding ``number`` to the base bet payload.

        Extends :meth:`Bet.to_dict` so the bound point round-trips alongside the
        id/type/amount/working fields shared by every bet.
        """
        base = super().to_dict()
        return {
            "id": base["id"],
            "type": base["type"],
            "amount": base["amount"],
            "working": base["working"],
            "number": self.number,
        }


class TakeOdds(_OddsBet):
    """Free Odds on the Pass side -- you "took" odds behind a Pass/Come bet.

    Wins when the point ``number`` is rolled before a 7, paying TRUE odds (no
    house edge). Live only during the POINT phase; on the come-out it is off
    (NO_ACTION). Loses on a seven-out.
    """

    def resolve(self, roll: DiceRoll, state: GameState) -> Resolution:
        """Settle the take-odds bet against one roll and the table phase."""
        # Off on the come-out: odds are not working until a point is set.
        if state.phase is not Phase.POINT:
            return Resolution(
                bet_id=self.id,
                status=ResolutionStatus.NO_ACTION,
                delta=self.amount * 0,
                note="odds off (come-out)",
            )

        total = roll.total
        if total == self.number:
            # Point made before the 7: win at TRUE odds (e.g. 4 -> 2:1).
            win_amount: Fraction = odds_ratio(take=True, number=self.number).payout(self.amount)
            return Resolution(
                bet_id=self.id,
                status=ResolutionStatus.WIN,
                delta=win_amount,
                note="take odds win",
            )
        if total == _SEVEN:
            # Seven-out: the odds bet loses its full stake.
            return Resolution(
                bet_id=self.id,
                status=ResolutionStatus.LOSE,
                delta=-self.amount,
                note="seven out",
            )
        # Any other total leaves the point standing: no action for this bet.
        return Resolution(
            bet_id=self.id,
            status=ResolutionStatus.NO_ACTION,
            delta=self.amount * 0,
            note="no action",
        )


class LayOdds(_OddsBet):
    """Free Odds on the Don't side -- you "laid" odds behind a Don't bet.

    Wins when a 7 is rolled before the point ``number``, paying the INVERSE true
    odds (e.g. 4 -> 1:2): the Don't bettor is the favorite and risks more to win
    less. Live only during the POINT phase; on the come-out it is off
    (NO_ACTION). Loses if the point is made.
    """

    def resolve(self, roll: DiceRoll, state: GameState) -> Resolution:
        """Settle the lay-odds bet against one roll and the table phase."""
        # Off on the come-out: odds are not working until a point is set.
        if state.phase is not Phase.POINT:
            return Resolution(
                bet_id=self.id,
                status=ResolutionStatus.NO_ACTION,
                delta=self.amount * 0,
                note="odds off (come-out)",
            )

        total = roll.total
        if total == _SEVEN:
            # Seven before the point: win at INVERSE true odds (e.g. 4 -> 1:2).
            win_amount: Fraction = odds_ratio(take=False, number=self.number).payout(self.amount)
            return Resolution(
                bet_id=self.id,
                status=ResolutionStatus.WIN,
                delta=win_amount,
                note="lay odds win",
            )
        if total == self.number:
            # Point made: the wrong-way odds bet loses its full stake.
            return Resolution(
                bet_id=self.id,
                status=ResolutionStatus.LOSE,
                delta=-self.amount,
                note="point made",
            )
        # Any other total leaves the point standing: no action for this bet.
        return Resolution(
            bet_id=self.id,
            status=ResolutionStatus.NO_ACTION,
            delta=self.amount * 0,
            note="no action",
        )
