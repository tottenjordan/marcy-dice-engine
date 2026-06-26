"""The Come bet: a Pass Line that travels on its OWN come-point.

A Come bet is mechanically identical to a :class:`~craps_engine.bets.line.PassLine`
wager, but it is placed AFTER a point is already established and it carries its
own private come-point rather than riding the table's point. Think of it as a
fresh Pass Line whose personal "come-out" is whatever roll immediately follows
placing it:

* While the come bet is still "coming" (its :attr:`come_point` is ``None``) it
  settles exactly like a Pass Line come-out -- a natural (7/11) WINS, a craps
  number (2/3/12) LOSES, and a point number (4,5,6,8,9,10) WOULD establish the
  come-point. NOTE the 7 and 12 asymmetry vs. the Don't Come side: for a COME
  bet the 7 WINS and the 12 LOSES (there is no bar 12 here).
* Once the come-point is set, the come bet races THAT number against the 7: the
  come-point WINS, a 7 LOSES (seven-out), everything else stands.

Because the bet rides its OWN come-point, :meth:`resolve` IGNORES the table
phase entirely -- it never reads ``state.phase`` or ``state.point``. The
``state`` argument is accepted only to satisfy the
:meth:`~craps_engine.bets.base.Bet.resolve` contract shared by every bet.

PURITY (critical contract)
--------------------------
:meth:`resolve` is strictly READ-ONLY: it never mutates :attr:`come_point` (nor
``state``). Establishing the come-point on a point-number roll is a SEPARATE,
LATER mutator -- it is deliberately NOT implemented here. The portfolio's static
EV matrix calls ``resolve`` repeatedly against the same bet instance, so any
mutation would corrupt those repeated evaluations.

Come pays even money (1:1), exactly like the Pass Line, so net winnings on a win
equal the stake. That payout is taken from the data-driven
:data:`~craps_engine.registry.REGISTRY` ``"pass_line"`` spec rather than being
hard-coded, so if the canonical odds ever change this code follows automatically.
"""

from __future__ import annotations

from fractions import Fraction
from typing import TYPE_CHECKING

from craps_engine.bets.base import Bet, BetPayload, Resolution, ResolutionStatus
from craps_engine.registry import REGISTRY

if TYPE_CHECKING:
    from craps_engine.dice import DiceRoll
    from craps_engine.state import GameState

# The come-point numbers a come bet may travel on. 7 and 11, and the craps
# numbers 2/3/12, are never points, so binding a come-point to them is rejected
# fail-fast (a repo convention).
_VALID_POINTS = frozenset({4, 5, 6, 8, 9, 10})

# Coming-state outcome sets, named once so the resolve logic reads like the
# rulebook (mirrors the Pass Line come-out vocabulary).
_PASS_NATURALS = frozenset({7, 11})  # Come WINS while coming.
_PASS_CRAPS = frozenset({2, 3, 12})  # Come LOSES while coming (12 is NOT barred).

# The seven, named for readability at its use sites.
_SEVEN = 7


class ComeBetPayload(BetPayload):
    """Serialized shape of a come bet: the base bet payload plus its come-point.

    Extends :class:`~craps_engine.bets.base.BetPayload` with the travelling
    ``come_point`` (``None`` while the bet is still coming) so the wager's
    private come-point round-trips through serialization.
    """

    come_point: int | None


class ComeBet(Bet):
    """A Come bet that rides its own come-point, oblivious to the table phase.

    Behaves like a Pass Line whose personal come-out is the roll after it is
    placed. In its "coming" state (:attr:`come_point` is ``None``) it wins on a
    natural (7/11), loses on craps (2/3/12), and a point number would establish
    its come-point (no money moves). Once the come-point is set it wins when that
    number is rolled and loses on a seven-out. Pays 1:1.

    Only the TRAVELING-state resolution is implemented here: the come-point
    ESTABLISHMENT mutator is a separate, later concern (see the module docstring),
    so :meth:`resolve` is strictly pure and never mutates :attr:`come_point`.
    """

    def __init__(
        self,
        id: str,  # noqa: A002 (mirrors Bet's public ``id`` name)
        amount: Fraction | int,
        *,
        come_point: int | None = None,
        working: bool = True,
    ) -> None:
        """Create a come bet, optionally already on a come-point.

        ``come_point`` is either ``None`` (the bet is still "coming") or a real
        point number (4,5,6,8,9,10); any other value is rejected fail-fast,
        naming the offending value. Stake validation/normalization is deferred to
        :class:`Bet`.
        """
        if come_point is not None and come_point not in _VALID_POINTS:
            msg = f"not a valid come point: {come_point} (valid points: 4, 5, 6, 8, 9, 10)"
            raise ValueError(msg)
        super().__init__(id, amount, working=working)
        #: The come-point this bet is travelling on, or ``None`` while coming.
        self.come_point = come_point

    def establish_come_point(self, total: int) -> bool:
        """Bind the come-point to ``total`` -- the ONLY mutation path for it.

        Establishment is funneled exclusively through this mutator so that
        :meth:`resolve` can stay strictly pure (it never sets
        :attr:`come_point`). Returns ``True`` and sets the come-point only when
        the bet is still coming (:attr:`come_point` is ``None``) AND ``total`` is
        a real point number (4,5,6,8,9,10). Otherwise -- already travelling, or
        ``total`` is a 7/11 or a craps number -- it leaves the bet untouched and
        returns ``False``.
        """
        if self.come_point is None and total in _VALID_POINTS:
            self.come_point = total
            return True
        return False

    def to_dict(self) -> ComeBetPayload:
        """Serialize, adding ``come_point`` to the base bet payload.

        Extends :meth:`Bet.to_dict` so the travelling come-point round-trips
        alongside the id/type/amount/working fields shared by every bet.
        """
        base = super().to_dict()
        return {
            "id": base["id"],
            "type": base["type"],
            "amount": base["amount"],
            "working": base["working"],
            "come_point": self.come_point,
        }

    def resolve(self, roll: DiceRoll, state: GameState) -> Resolution:
        """Settle the come bet against one roll, IGNORING the table phase.

        Pure and read-only: never mutates :attr:`come_point` or ``state``. The
        ``state`` argument is unused (a come bet rides its own come-point) and is
        present only to honor the shared :meth:`Bet.resolve` signature.
        """
        # The come bet is oblivious to the table phase; ``state`` is intentionally
        # unused here (kept for the shared resolve signature).
        del state
        total = roll.total
        # Even-money net winnings for this stake (1:1 -> equals the stake), kept
        # data-driven via the Pass Line registry payout rather than hard-coded.
        win_amount: Fraction = REGISTRY["pass_line"].payout.payout(self.amount)

        if self.come_point is None:
            # COMING state: decided immediately like a Pass Line come-out.
            if total in _PASS_NATURALS:
                return Resolution(
                    bet_id=self.id,
                    status=ResolutionStatus.WIN,
                    delta=win_amount,
                    note=f"natural {total}",
                )
            if total in _PASS_CRAPS:
                return Resolution(
                    bet_id=self.id,
                    status=ResolutionStatus.LOSE,
                    delta=-self.amount,
                    note=f"craps {total}",
                )
            # A point number (4,5,6,8,9,10): this WOULD establish the come-point,
            # but no money moves and we do NOT mutate here (establishment is a
            # later, separate mutator). Report no action.
            return Resolution(
                bet_id=self.id,
                status=ResolutionStatus.NO_ACTION,
                delta=Fraction(0),
                note="come point established",
            )

        # ESTABLISHED state: race the come-point against the 7.
        if total == self.come_point:
            # Come-point made: the come bettor wins.
            return Resolution(
                bet_id=self.id,
                status=ResolutionStatus.WIN,
                delta=win_amount,
                note="come point made",
            )
        if total == _SEVEN:
            # Seven-out: the come bet loses its full stake.
            return Resolution(
                bet_id=self.id,
                status=ResolutionStatus.LOSE,
                delta=-self.amount,
                note="seven out",
            )
        # Any other total leaves the come-point standing: no action for this bet.
        return Resolution(
            bet_id=self.id,
            status=ResolutionStatus.NO_ACTION,
            delta=Fraction(0),
            note="no action",
        )
