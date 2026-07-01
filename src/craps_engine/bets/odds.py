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

Both settle at true odds during :attr:`~craps_engine.state.Phase.POINT`. On the
come-out the odds are OFF BY DEFAULT, mirroring real table rules where a player's
odds are not working on the come-out unless they explicitly call them on. This
matters for odds backing a COME point (pass-side odds never survive to a
come-out, since a made/lost puck point ends the cycle): while off, a come-point
or a 7 on the come-out RETURNS the odds to the player (a ``PUSH`` that
:meth:`_OddsBet.remains_on_table` takes down) rather than winning or losing, and
any other total leaves them standing. A player can call the odds on for the
come-out via the ``come_out_working`` flag, after which they settle normally. The
exact ratios come from :func:`craps_engine.registry.odds_ratio` rather than being
hard-coded here, so the engine has one source of truth for true odds.

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
    ``number`` and the ``come_out_working`` flag (whether the player has called
    these odds ON for the come-out) so both round-trip through serialization.
    """

    number: int
    come_out_working: bool


# The point numbers a Free Odds bet may back. Only the 7 is never a point, so
# binding odds to it is rejected fail-fast. 2/3/11/12 ARE oddsable under crapless
# craps; ruleset-specific legality is enforced upstream in the PlayController.
_VALID_POINTS = frozenset({2, 3, 4, 5, 6, 8, 9, 10, 11, 12})

# The seven, named for readability at its use sites.
_SEVEN = 7

#: Max-odds multipliers by point number, kept as DOCUMENTATION only. The engine
#: does NOT enforce these at resolution time -- validating a stake against the
#: table maximum is a table-rules concern (the PlayController's placement hook),
#: not part of how an odds bet settles. The values follow a uniform "max win =
#: 6x the flat bet" rule: the standard 3-4-5x cap (3x on 4/10 at 2:1, 4x on 5/9
#: at 3:2, 5x on 6/8 at 6:5 all win 6x flat) extends to the crapless points so
#: their max win matches -- 1x on 2/12 (6:1) and 2x on 3/11 (3:1).
MAX_ODDS_MULTIPLIER: dict[int, int] = {
    4: 3,
    10: 3,
    5: 4,
    9: 4,
    6: 5,
    8: 5,
    2: 1,  # crapless: 1x at 6:1 wins 6x flat
    12: 1,
    3: 2,  # crapless: 2x at 3:1 wins 6x flat
    11: 2,
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
        come_out_working: bool = False,
    ) -> None:
        """Create an odds bet bound to a point ``number``.

        Rejects the 7 (the only total that is never a point) fail-fast, then
        defers stake validation/normalization to :class:`Bet`.

        ``come_out_working`` defaults to ``False`` -- the real-table default that
        odds ride OFF on the come-out. It matters only for odds backing a COME
        point (pass-side odds never survive to a come-out): when it is off, a
        come-point or a 7 on the come-out RETURNS the odds to the player instead
        of settling them (see :meth:`TakeOdds.resolve`). A player may call the
        odds on for the come-out by flipping this to ``True``.
        """
        if number not in _VALID_POINTS:
            msg = f"not a valid point number: {number} (7 is never a point)"
            raise ValueError(msg)
        super().__init__(id, amount, working=working)
        #: The point number this odds bet is backing.
        self.number = number
        #: Whether these odds have been called ON for the come-out roll.
        self.come_out_working = come_out_working

    def remains_on_table(self, resolution: Resolution, roll: DiceRoll) -> bool:
        """Keep the odds up only while UNRESOLVED (NO_ACTION); else take them down.

        Overrides the base rule (which keeps both NO_ACTION and PUSH) because an
        odds bet only ever PUSHes to signal a come-out RETURN -- the come-point or
        a 7 landed on the come-out while the odds were off, so the stake goes back
        to the player and the bet comes down. WIN/LOSE come down as usual; only a
        genuine NO_ACTION (the roll didn't touch the odds) leaves them standing.
        """
        del roll  # The status alone decides for odds.
        return resolution.status is ResolutionStatus.NO_ACTION

    def _come_out_off(self, state: GameState) -> bool:
        """Whether these odds are OFF right now (on the come-out, not called on)."""
        return state.phase is not Phase.POINT and not self.come_out_working

    def _off_resolution(self, roll: DiceRoll) -> Resolution:
        """Settle an OFF come-out roll: RETURN on the come-point/7, else stand.

        With the odds off, a come-point or a 7 on the come-out returns the stake
        to the player (a PUSH that :meth:`remains_on_table` then takes down); any
        other total leaves the odds standing untouched (NO_ACTION).
        """
        if roll.total in (self.number, _SEVEN):
            return Resolution(
                bet_id=self.id,
                status=ResolutionStatus.PUSH,
                delta=self.amount * 0,
                note="odds off (come-out) — returned",
            )
        return Resolution(
            bet_id=self.id,
            status=ResolutionStatus.NO_ACTION,
            delta=self.amount * 0,
            note="odds off (come-out)",
        )

    def to_dict(self) -> OddsBetPayload:
        """Serialize, adding ``number`` + ``come_out_working`` to the base payload.

        Extends :meth:`Bet.to_dict` so the bound point and the come-out working
        flag round-trip alongside the id/type/amount/working fields shared by
        every bet.
        """
        base = super().to_dict()
        return {
            "id": base["id"],
            "type": base["type"],
            "amount": base["amount"],
            "working": base["working"],
            "number": self.number,
            "come_out_working": self.come_out_working,
        }


class TakeOdds(_OddsBet):
    """Free Odds on the Pass side -- you "took" odds behind a Pass/Come bet.

    Wins when the point ``number`` is rolled before a 7, paying TRUE odds (no
    house edge). Live only during the POINT phase; on the come-out it is off
    (NO_ACTION). Loses on a seven-out.
    """

    def resolve(self, roll: DiceRoll, state: GameState) -> Resolution:
        """Settle the take-odds bet against one roll and the table phase.

        Off on the come-out by default (:meth:`_come_out_off`): a come-point or a
        7 there returns the odds, any other total leaves them standing. During the
        point phase -- or on the come-out once the player has called them ON
        (``come_out_working``) -- the bet settles at true odds by racing its
        backed ``number`` against the 7, which is correct whether ``number`` is
        the puck point (pass-side odds) or a travelled come-point (come odds).
        """
        if self._come_out_off(state):
            return self._off_resolution(roll)

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
        """Settle the lay-odds bet against one roll and the table phase.

        Off on the come-out by default (:meth:`_come_out_off`): a come-point or a
        7 there returns the odds, any other total leaves them standing. During the
        point phase -- or on the come-out once the player has called them ON
        (``come_out_working``) -- the bet settles at inverse true odds by racing
        the 7 against its backed ``number`` (the puck point for pass-side lay
        odds, or a travelled come-point for don't-come odds).
        """
        if self._come_out_off(state):
            return self._off_resolution(roll)

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
