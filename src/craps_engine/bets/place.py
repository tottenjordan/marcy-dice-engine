"""Place bets on the box numbers 4, 5, 6, 8, 9, 10.

A Place bet is a standing wager on a single number. It WINS at PLACE odds (which
pay LESS than true odds, hence the house edge) whenever its number is rolled, and
LOSES its full stake whenever a 7 is rolled. Every other total leaves it
standing (NO_ACTION). The exact payout ratios come from
:func:`craps_engine.registry.place_spec` (6/8 -> 7:6, 5/9 -> 7:5, 4/10 -> 9:5),
so the engine has one source of truth for place odds.

THE COME-OUT "OFF" CONVENTION (the subtle, important part)
---------------------------------------------------------
By long-standing craps table convention, Place bets are OFF (not working) on the
COME-OUT roll by default. The reasoning at a real table: a come-out 7 is a WIN
for the Pass-line crowd, so the casino leaves place bets idle then so that same 7
does not simultaneously sweep every place bet off the felt. The player may
explicitly turn their place bets ON for the come-out ("place bets working"), in
which case they win/lose normally on that roll.

We model this with the ``working`` flag already on :class:`Bet` PLUS the table
phase. The EFFECTIVE working state for a single roll is:

    live  <=>  state.phase is POINT
               OR (state.phase is COME_OUT AND self.working is True)

So during the POINT phase a place bet is always live (the ``working`` flag is
irrelevant then); only on the come-out does ``working`` decide whether it acts.
Because the default should be OFF on the come-out, :class:`PlaceBet` overrides
the base :class:`Bet` default to ``working=False``.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from craps_engine.bets.base import Bet, BetPayload, Resolution, ResolutionStatus
from craps_engine.registry import place_spec
from craps_engine.state import Phase

if TYPE_CHECKING:
    from fractions import Fraction

    from craps_engine.dice import DiceRoll
    from craps_engine.state import GameState


class PlaceBetPayload(BetPayload):
    """Serialized shape of a place bet: the base bet payload plus its number.

    Extends :class:`~craps_engine.bets.base.BetPayload` with the placed
    ``number`` so the wager's target box number round-trips through
    serialization.
    """

    number: int


# The box numbers a place bet may sit on. 7 and 11, and the craps numbers
# 2/3/12, can never be placed, so binding a place bet to them is rejected
# fail-fast (a repo convention). ``place_spec`` is the ultimate source of truth
# for validity; this mirrors it locally so construction fails before resolution.
_VALID_PLACE_NUMBERS = frozenset({4, 5, 6, 8, 9, 10})

# The seven-out total, named for readability at its use site.
_SEVEN = 7


class PlaceBet(Bet):
    """A standing wager on a single box number (4, 5, 6, 8, 9, 10).

    Wins at PLACE odds when its ``number`` is rolled and loses its stake on a 7.
    OFF (not working) on the come-out by default -- see the module docstring for
    the come-out convention -- so it defaults to ``working=False``.
    """

    def __init__(
        self,
        id: str,  # noqa: A002 (mirrors Bet's public ``id`` name)
        number: int,
        amount: Fraction | int,
        *,
        working: bool = False,
    ) -> None:
        """Create a place bet on ``number``.

        Rejects any ``number`` that is not a real box number (4,5,6,8,9,10)
        fail-fast, then defers stake validation/normalization to :class:`Bet`.
        Note the ``working`` default is ``False`` (OFF on the come-out), which
        deliberately differs from the base :class:`Bet` default of ``True``.
        """
        if number not in _VALID_PLACE_NUMBERS:
            msg = f"cannot place {number}: valid place numbers are 4, 5, 6, 8, 9, 10"
            raise ValueError(msg)
        super().__init__(id, amount, working=working)
        #: The box number this place bet sits on.
        self.number = number

    def _is_live(self, state: GameState) -> bool:
        """Whether this place bet acts on the current roll (the come-out rule).

        Live during the POINT phase unconditionally; live on the COME-OUT only
        when the player has explicitly turned the bet on (``working=True``).
        """
        if state.phase is Phase.POINT:
            return True
        # COME_OUT: only live if the player turned the place bet on.
        return self.working

    def remains_on_table(self, resolution: Resolution, roll: DiceRoll) -> bool:
        """Keep a place bet up after a WIN too -- it is a STANDING wager.

        A place bet stays on the felt after its number hits (the stake remains
        working, ready to win again), so it differs from the base
        :meth:`Bet.remains_on_table` default by ALSO surviving a WIN. It still
        stays up on NO_ACTION/PUSH and only comes down on a LOSE (the seven-out
        that sweeps it). ``roll`` is unused (the status alone decides) but is kept
        for the shared hook signature.
        """
        del roll  # Keying only on the resolution status.
        return resolution.status in {
            ResolutionStatus.WIN,
            ResolutionStatus.NO_ACTION,
            ResolutionStatus.PUSH,
        }

    def to_dict(self) -> PlaceBetPayload:
        """Serialize, adding ``number`` to the base bet payload.

        Extends :meth:`Bet.to_dict` so the placed box number round-trips
        alongside the id/type/amount/working fields shared by every bet.
        """
        base = super().to_dict()
        return {
            "id": base["id"],
            "type": base["type"],
            "amount": base["amount"],
            "working": base["working"],
            "number": self.number,
        }

    def resolve(self, roll: DiceRoll, state: GameState) -> Resolution:
        """Settle the place bet against one roll and the table phase."""
        # OFF on the come-out (unless turned on): the bet neither wins nor loses,
        # it simply does not act this roll. See the module docstring.
        if not self._is_live(state):
            return Resolution(
                bet_id=self.id,
                status=ResolutionStatus.NO_ACTION,
                delta=self.amount * 0,
                note="place off (come-out)",
            )

        total = roll.total
        if total == self.number:
            # The placed number hit: win at PLACE odds (e.g. place 6 -> 7:6).
            win_amount: Fraction = place_spec(self.number).payout.payout(self.amount)
            return Resolution(
                bet_id=self.id,
                status=ResolutionStatus.WIN,
                delta=win_amount,
                note=f"place {self.number} hit",
            )
        if total == _SEVEN:
            # Seven-out: the place bet loses its full stake.
            return Resolution(
                bet_id=self.id,
                status=ResolutionStatus.LOSE,
                delta=-self.amount,
                note="seven out",
            )
        # Any other total leaves the place bet standing: no action this roll.
        return Resolution(
            bet_id=self.id,
            status=ResolutionStatus.NO_ACTION,
            delta=self.amount * 0,
            note="no action",
        )
