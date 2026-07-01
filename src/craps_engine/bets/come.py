"""Come-family bets: :class:`ComeBet` and :class:`DontCome`.

A Come-family bet is mechanically a line bet that travels on its OWN
come-point. It is placed AFTER a point is already established and it carries
its own private come-point rather than riding the table's point. Think of it as
a fresh line bet whose personal "come-out" is whatever roll immediately follows
placing it:

* :class:`ComeBet` mirrors a :class:`~craps_engine.bets.line.PassLine`. While
  it is still "coming" (its :attr:`~_ComeBet.come_point` is ``None``) it settles
  exactly like a Pass Line come-out -- a natural (7/11) WINS, a craps number
  (2/3/12) LOSES, and a point number (4,5,6,8,9,10) WOULD establish the
  come-point. Once the come-point is set the come-point WINS and a 7 LOSES.
* :class:`DontCome` mirrors a :class:`~craps_engine.bets.line.DontPass`. While
  coming it WINS on 2/3, LOSES on 7/11, and PUSHES on 12 (the BAR). Once the
  come-point is set a 7 WINS (seven-out) and the come-point LOSES. Note the 7
  and 12 asymmetry vs. the Come side and the bar-12 push that trims the Don't
  edge below the Pass edge.

Because each bet rides its OWN come-point, :meth:`resolve` IGNORES the table
phase entirely -- it never reads ``state.phase`` or ``state.point``. The
``state`` argument is accepted only to satisfy the
:meth:`~craps_engine.bets.base.Bet.resolve` contract shared by every bet.

PURITY (critical contract)
--------------------------
:meth:`resolve` is strictly READ-ONLY on every Come-family bet: it never
mutates :attr:`~_ComeBet.come_point` (nor ``state``). Establishing the
come-point on a point-number roll is a SEPARATE, LATER mutator
(:meth:`~_ComeBet.establish_come_point`). The portfolio's static EV matrix calls
``resolve`` repeatedly against the same bet instance, so any mutation would
corrupt those repeated evaluations.

Both sides pay even money (1:1): the Come side via the data-driven
:data:`~craps_engine.registry.REGISTRY` ``"pass_line"`` spec, the Don't Come
side via ``"dont_pass"``, rather than hard-coding the stake, so if the canonical
odds ever change this code follows automatically.
"""

from __future__ import annotations

from fractions import Fraction
from typing import TYPE_CHECKING

from craps_engine.bets.base import Bet, BetPayload, Resolution, ResolutionStatus
from craps_engine.registry import REGISTRY

if TYPE_CHECKING:
    from craps_engine.dice import DiceRoll
    from craps_engine.state import GameState

# The come-point numbers a Come-family bet may travel on. Only 7 is never a
# point under any supported ruleset (it is the seven-out / the crapless natural),
# so binding a come-point to it is rejected fail-fast (a repo convention). The
# craps numbers 2/3/12 and the 11 ARE valid come-points under crapless craps;
# whether a given roll actually establishes one is decided ruleset-correctly by
# :meth:`resolve` (which reads ``state.ruleset``) and gated in :meth:`advance` on
# a NO_ACTION resolution -- never by this set alone.
_VALID_POINTS = frozenset({2, 3, 4, 5, 6, 8, 9, 10, 11, 12})

# Don't Come coming-state outcome sets, named once so its resolve logic reads
# like the rulebook (Don't Come is a standard-only bet, so these stay fixed).
_PASS_NATURALS = frozenset({7, 11})  # Don't Come LOSES while coming.
_DONT_WIN_CRAPS = frozenset({2, 3})  # Don't Come WINS while coming (12 is barred).

# The barred come-out total: a Don't Come PUSH, never a win.
_BAR_NUMBER = 12

# The seven, named for readability at its use sites.
_SEVEN = 7


class _ComeBetPayload(BetPayload):
    """Serialized shape of a Come-family bet: the base payload plus its come-point.

    Extends :class:`~craps_engine.bets.base.BetPayload` with the travelling
    ``come_point`` (``None`` while the bet is still coming) so the wager's
    private come-point round-trips through serialization. The base
    :meth:`Bet.to_dict` fills ``type`` from the concrete class name, so the same
    payload shape serves both subclasses.
    """

    come_point: int | None


#: Backwards-compatible alias for the come-family payload (the original name).
ComeBetPayload = _ComeBetPayload
#: Don't Come shares the come-family payload shape (only ``type`` differs).
DontComePayload = _ComeBetPayload


class _ComeBet(Bet):
    """Shared base for the two Come-family bets: stores/validates the come-point.

    Both bets carry, beyond the base :class:`Bet` fields, a private
    :attr:`come_point` they travel on. This base centralizes that field's
    validation (it must be a real point), the establishment mutator, and
    serialization so the concrete subclasses differ ONLY in their resolve rules.

    :meth:`resolve` is intentionally NOT implemented here: it stays abstract
    (inherited from :class:`Bet`, an ABC), so each subclass supplies its own
    rule-set and ``_ComeBet`` itself cannot be instantiated.
    """

    def __init__(
        self,
        id: str,  # noqa: A002 (mirrors Bet's public ``id`` name)
        amount: Fraction | int,
        *,
        come_point: int | None = None,
        working: bool = True,
    ) -> None:
        """Create a Come-family bet, optionally already on a come-point.

        ``come_point`` is either ``None`` (the bet is still "coming") or a real
        point number (4,5,6,8,9,10); any other value is rejected fail-fast,
        naming the offending value. Stake validation/normalization is deferred to
        :class:`Bet`.
        """
        if come_point is not None and come_point not in _VALID_POINTS:
            msg = f"not a valid come point: {come_point} (7 is never a come point)"
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
        a valid come-point (anything but a 7). Otherwise -- already travelling, or
        ``total`` is a 7 -- it leaves the bet untouched and returns ``False``.
        Whether a given roll *should* establish is decided ruleset-correctly by
        :meth:`advance` (gated on a NO_ACTION resolution), so this mutator only
        guards the universal 7 case.
        """
        if self.come_point is None and total in _VALID_POINTS:
            self.come_point = total
            return True
        return False

    def advance(self, roll: DiceRoll, resolution: Resolution) -> None:
        """Establish the come-point when the roll had no action (the travelling step).

        The come family's per-roll transition. :meth:`resolve` is ruleset-aware,
        so a NO_ACTION result while the bet is still coming means exactly "this
        total establishes the come-point under the active ruleset" -- standard:
        4/5/6/8/9/10; crapless: any total but a 7. Keying establishment on the
        resolution STATUS (rather than a hard-coded point set) keeps a standard
        come bet that LOSES on a craps total from ever briefly binding a
        come-point. Both subclasses inherit this, so :meth:`resolve` stays pure.
        """
        if resolution.status is ResolutionStatus.NO_ACTION:
            self.establish_come_point(roll.total)

    def to_dict(self) -> _ComeBetPayload:
        """Serialize, adding ``come_point`` to the base bet payload.

        Extends :meth:`Bet.to_dict` so the travelling come-point round-trips
        alongside the id/type/amount/working fields shared by every bet. The
        ``type`` comes from the concrete class name, so the same payload reads as
        ``"ComeBet"`` or ``"DontCome"`` automatically.
        """
        base = super().to_dict()
        return {
            "id": base["id"],
            "type": base["type"],
            "amount": base["amount"],
            "working": base["working"],
            "come_point": self.come_point,
        }


class ComeBet(_ComeBet):
    """A Come bet that rides its own come-point, oblivious to the table phase.

    Behaves like a Pass Line whose personal come-out is the roll after it is
    placed. In its "coming" state (:attr:`come_point` is ``None``) it wins on a
    natural (7/11), loses on craps (2/3/12), and a point number would establish
    its come-point (no money moves). Once the come-point is set it wins when that
    number is rolled and loses on a seven-out. Pays 1:1.

    Only the TRAVELING-state resolution is implemented here: the come-point
    ESTABLISHMENT mutator lives on :class:`_ComeBet`, so :meth:`resolve` is
    strictly pure and never mutates :attr:`come_point`.
    """

    def resolve(self, roll: DiceRoll, state: GameState) -> Resolution:
        """Settle the come bet against one roll, IGNORING the table phase.

        Pure and read-only: never mutates :attr:`come_point` or ``state``. The
        come bet ignores the table PHASE (it rides its own come-point), but while
        coming it consults ``state.ruleset`` for the come-out naturals/craps so it
        behaves like a Pass Line come-out under the active variant (standard: 7/11
        win, 2/3/12 lose; crapless: only 7 wins, nothing craps out).
        """
        total = roll.total
        # Even-money net winnings for this stake (1:1 -> equals the stake), kept
        # data-driven via the Pass Line registry payout rather than hard-coded.
        win_amount: Fraction = REGISTRY["pass_line"].payout.payout(self.amount)

        if self.come_point is None:
            # COMING state: decided immediately like a Pass Line come-out, using
            # the active ruleset's naturals/craps.
            if total in state.ruleset.pass_naturals:
                return Resolution(
                    bet_id=self.id,
                    status=ResolutionStatus.WIN,
                    delta=win_amount,
                    note=f"natural {total}",
                )
            if total in state.ruleset.pass_craps:
                return Resolution(
                    bet_id=self.id,
                    status=ResolutionStatus.LOSE,
                    delta=-self.amount,
                    note=f"craps {total}",
                )
            # A point number: this WOULD establish the come-point, but no money
            # moves and we do NOT mutate here (establishment is a later, separate
            # mutator). Report no action.
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


class DontCome(_ComeBet):
    """A Don't Come bet that rides its own come-point, bar 12.

    The wrong-way mirror of :class:`ComeBet`, behaving like a Don't Pass whose
    personal come-out is the roll after it is placed. In its "coming" state
    (:attr:`come_point` is ``None``) it WINS on 2/3, LOSES on 7/11, and PUSHES on
    12 (the bar); a point number would establish its come-point (no money moves).
    Once the come-point is set a 7 WINS (seven-out) and the come-point LOSES.
    Pays 1:1 via the Don't Pass payout. The barred 12 is exactly what trims the
    Don't side's edge below the Come side's.

    Establishment lives on :class:`_ComeBet`, so :meth:`resolve` is strictly pure
    and never mutates :attr:`come_point`.
    """

    def resolve(self, roll: DiceRoll, state: GameState) -> Resolution:
        """Settle the don't-come bet against one roll, IGNORING the table phase.

        Pure and read-only: never mutates :attr:`come_point` or ``state``. The
        ``state`` argument is unused (the bet rides its own come-point) and is
        present only to honor the shared :meth:`Bet.resolve` signature. The
        coming/established split is delegated to helpers so each stays within the
        branch-count limit (mirroring Don't Pass).
        """
        # The don't-come bet is oblivious to the table phase; ``state`` is
        # intentionally unused here (kept for the shared resolve signature).
        del state
        if self.come_point is None:
            return self._resolve_coming(roll)
        return self._resolve_established(roll)

    def _resolve_coming(self, roll: DiceRoll) -> Resolution:
        """Settle the don't-come bet while still coming (bar 12).

        The inverse of the Come side, EXCEPT the 12 is barred -- it pushes
        instead of winning, which is precisely what trims the Don't edge.
        """
        total = roll.total
        # Even-money net winnings (1:1), data-driven via the Don't Pass payout.
        win_amount: Fraction = REGISTRY["dont_pass"].payout.payout(self.amount)
        if total in _DONT_WIN_CRAPS:
            return Resolution(
                bet_id=self.id,
                status=ResolutionStatus.WIN,
                delta=win_amount,
                note=f"craps {total}",
            )
        if total in _PASS_NATURALS:
            # 7/11: a natural beats the don't-come bettor while coming.
            return Resolution(
                bet_id=self.id,
                status=ResolutionStatus.LOSE,
                delta=-self.amount,
                note=f"natural {total}",
            )
        if total == _BAR_NUMBER:
            # Bar 12: stand-off. Stake returned, no net change (NOT a loss).
            return Resolution(
                bet_id=self.id,
                status=ResolutionStatus.PUSH,
                delta=Fraction(0),
                note="bar 12 push",
            )
        # A point number (4,5,6,8,9,10): this WOULD establish the come-point, but
        # no money moves and we do NOT mutate here. Report no action.
        return Resolution(
            bet_id=self.id,
            status=ResolutionStatus.NO_ACTION,
            delta=Fraction(0),
            note="come point established",
        )

    def _resolve_established(self, roll: DiceRoll) -> Resolution:
        """Settle the don't-come bet once its come-point is set.

        The wrong-way bettor now backs the 7 against their come-point: a 7 WINS
        (seven-out) and the come-point LOSES.
        """
        total = roll.total
        # Even-money net winnings (1:1), data-driven via the Don't Pass payout.
        win_amount: Fraction = REGISTRY["dont_pass"].payout.payout(self.amount)
        if total == _SEVEN:
            # Seven-out: the wrong-way bettor wins.
            return Resolution(
                bet_id=self.id,
                status=ResolutionStatus.WIN,
                delta=win_amount,
                note="seven out",
            )
        if total == self.come_point:
            # Come-point made: the don't-come bettor loses.
            return Resolution(
                bet_id=self.id,
                status=ResolutionStatus.LOSE,
                delta=-self.amount,
                note="come point made",
            )
        # Any other total leaves the come-point standing: no action for this bet.
        return Resolution(
            bet_id=self.id,
            status=ResolutionStatus.NO_ACTION,
            delta=Fraction(0),
            note="no action",
        )
