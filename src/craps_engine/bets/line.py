"""The two flat line bets: :class:`PassLine` and :class:`DontPass`.

A line bet is the spine of a craps round. It is placed before the come-out and
lives across the entire come-out-to-resolution sequence, settling in two very
different regimes:

* On the COME-OUT roll it is decided immediately by a natural (7/11) or a craps
  number (2/3/12).
* Once a point is established it races that point against the 7 -- the *opposite*
  wager for the two sides.

Pass and Don't Pass are near mirror images. The asymmetry that makes the Don't
side fractionally better is the *bar 12*: on the come-out the Don't bettor would
otherwise win on the 12, but the house pushes it instead (stake returned, no
win). That single barred outcome is the entire difference between the Pass edge
(7/495) and the Don't edge (3/220). NOTE: it is also why, once a point is set,
the Don't bettor is the statistical FAVORITE (more ways to roll a 7 than to make
any point) -- but that favorite-after-the-point property is an ANALYSIS concern
for the portfolio/EV layer; here we only encode the win/lose/push rules.

Both pay even money (1:1), so for a stake ``A`` the net winnings on a win are
exactly ``A``. We compute that via the data-driven payout in
:data:`~craps_engine.registry.REGISTRY` rather than hard-coding ``self.amount``,
so if the canonical odds ever change this code follows automatically.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from craps_engine.bets.base import Bet, Resolution, ResolutionStatus
from craps_engine.registry import REGISTRY
from craps_engine.state import Phase

if TYPE_CHECKING:
    from fractions import Fraction

    from craps_engine.dice import DiceRoll
    from craps_engine.state import GameState

# Come-out outcome sets for the Don't side, named once so its resolve logic reads
# like the rulebook. (PassLine reads its naturals/craps from ``state.ruleset`` so
# it can honor rules variants; Don't Pass is a standard-only bet.)
_PASS_NATURALS = frozenset({7, 11})  # Don't loses on the come-out.
_DONT_WIN_CRAPS = frozenset({2, 3})  # Don't wins on the come-out (12 is barred).
_BAR_NUMBER = 12  # The barred come-out total: a Don't PUSH, never a win.
_SEVEN = 7  # The seven, named for readability at its use sites.


class PassLine(Bet):
    """The Pass Line ("Front Line") bet -- the classic right-way wager.

    Wins on a come-out natural (7/11), loses on come-out craps (2/3/12), and
    otherwise rides the established point: it wins if the point is made and loses
    on a seven-out. Pays 1:1. Inherits :meth:`~craps_engine.bets.base.Bet.to_dict`
    and ``__init__`` (id, amount, working) from :class:`Bet`.
    """

    def resolve(self, roll: DiceRoll, state: GameState) -> Resolution:
        """Settle the Pass Line against one roll and the current table phase."""
        total = roll.total
        # Even-money net winnings for this stake (1:1 -> equals the stake), kept
        # data-driven via the registry payout rather than hard-coded.
        win_amount: Fraction = REGISTRY["pass_line"].payout.payout(self.amount)

        if state.phase is Phase.COME_OUT:
            # COME-OUT: decided immediately by the active ruleset's naturals vs
            # craps; a point number just establishes the point and leaves this bet
            # untouched (crapless: only 7 is a natural, nothing craps out).
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
            # A point number: the point is being established, so the Pass Line has
            # no action this roll -- it now rides that point.
            return Resolution(
                bet_id=self.id,
                status=ResolutionStatus.NO_ACTION,
                delta=self.amount * 0,
                note="point established",
            )

        # POINT phase: the bet races the point against the 7.
        if total == state.point:
            # Point made: the right-way bettor wins.
            return Resolution(
                bet_id=self.id,
                status=ResolutionStatus.WIN,
                delta=win_amount,
                note="point made",
            )
        if total == _SEVEN:
            # Seven-out: the round ends against the Pass bettor.
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


class DontPass(Bet):
    """The Don't Pass ("Back Line") bet -- the wrong-way wager, bar 12.

    The near-mirror of :class:`PassLine`: on the come-out it WINS on 2/3, LOSES
    on 7/11, and PUSHES on 12 (the bar). Once a point is set it wins on the
    seven-out and loses if the point is made. Pays 1:1. The barred 12 is the
    whole reason the Don't side carries a slightly smaller house edge than Pass.
    """

    def resolve(self, roll: DiceRoll, state: GameState) -> Resolution:
        """Settle the Don't Pass against one roll and the current table phase."""
        if state.phase is Phase.COME_OUT:
            # The come-out has four distinct outcomes; split it into its own
            # helper so each method stays within the branch-count limit and the
            # bar-12 special case reads clearly.
            return self._resolve_come_out(roll)
        return self._resolve_point(roll, state)

    def _resolve_come_out(self, roll: DiceRoll) -> Resolution:
        """Settle the Don't Pass on a come-out roll (bar 12).

        The Don't side is the inverse of Pass, EXCEPT the 12 is barred -- it
        pushes instead of winning, which is precisely what trims the Don't edge
        below the Pass edge.
        """
        total = roll.total
        # Even-money net winnings (1:1), data-driven via the registry payout.
        win_amount: Fraction = REGISTRY["dont_pass"].payout.payout(self.amount)
        if total in _DONT_WIN_CRAPS:
            return Resolution(
                bet_id=self.id,
                status=ResolutionStatus.WIN,
                delta=win_amount,
                note=f"craps {total}",
            )
        if total in _PASS_NATURALS:
            # 7/11: a natural beats the Don't bettor on the come-out.
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
                delta=self.amount * 0,
                note="bar 12 push",
            )
        # A point number: the point is established and the Don't bet rides it.
        return Resolution(
            bet_id=self.id,
            status=ResolutionStatus.NO_ACTION,
            delta=self.amount * 0,
            note="point established",
        )

    def _resolve_point(self, roll: DiceRoll, state: GameState) -> Resolution:
        """Settle the Don't Pass while a point is established."""
        total = roll.total
        # Even-money net winnings (1:1), data-driven via the registry payout.
        win_amount: Fraction = REGISTRY["dont_pass"].payout.payout(self.amount)
        # POINT phase: the Don't bettor is now backing the 7 against the point
        # (and is statistically the favorite -- analysis layer's concern).
        if total == _SEVEN:
            # Seven-out: the wrong-way bettor wins.
            return Resolution(
                bet_id=self.id,
                status=ResolutionStatus.WIN,
                delta=win_amount,
                note="seven out",
            )
        if total == state.point:
            # Point made: the Don't bettor loses.
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
