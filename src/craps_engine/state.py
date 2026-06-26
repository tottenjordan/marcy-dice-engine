"""Table-level come-out / point game state machine.

This module models ONLY the shared, table-wide phase of a craps round: whether
the table is on the come-out roll or has an established point, and what that
point is. :class:`GameState` is intentionally minimal -- it tracks the phase and
the point number, nothing else.

Deliberately out of scope (and why):

* Win/loss of LINE BETS on the come-out (a natural 7/11 win, a 2/3/12 craps
  loss) is the *bet's* concern, not the state machine's. The come-out 7 does not
  change the table phase, so the state machine treats every non-point come-out
  total identically -- it just stays on come-out. Bets read the transition (and
  the rolled total) to settle themselves.
* Come / Don't Come bets (Phase 2 of the plan) will introduce additional,
  PER-BET "sub-points" that travel with an individual wager and are layered on
  top of this base phase. This class is purposely the table-level phase only and
  is designed to be extended -- the per-bet sub-point logic will live with those
  bets, consulting this machine for the table phase rather than replacing it.
"""

from __future__ import annotations

import enum
from dataclasses import dataclass
from typing import TypedDict

# Inclusive bounds on a two-die total. Any total outside this range is impossible
# and is rejected fail-fast (a repo convention) so a bad value can never drive
# the phase logic.
_MIN_TOTAL = 2
_MAX_TOTAL = 12

# The "point numbers": come-out totals that establish a point. The complement
# within 2..12 (namely 2, 3, 7, 11, 12) are come-out naturals/craps that leave
# the table on come-out.
_POINT_NUMBERS = frozenset({4, 5, 6, 8, 9, 10})

# The seven-out total, named for readability at its single use site.
_SEVEN = 7


class Phase(enum.Enum):
    """The table-level phase of a craps round.

    Values are stable strings so :meth:`GameState.to_dict` and
    :meth:`PhaseTransition.to_dict` can emit them directly and any UI /
    Monte-Carlo layer consumes one fixed shape.
    """

    COME_OUT = "come_out"
    POINT = "point"


class PhaseTransitionPayload(TypedDict):
    """Serialized shape of a :class:`PhaseTransition`.

    Phases are emitted as their stable string values; everything else is a
    JSON-friendly primitive (``point`` may be ``None`` when back on come-out).
    """

    previous: str
    current: str
    point: int | None
    point_established: bool
    point_made: bool
    seven_out: bool


@dataclass(frozen=True)
class PhaseTransition:
    """An immutable record of what one rolled total did to the table phase.

    A transition is the structured return value of :meth:`GameState.apply`: it
    captures the phase before and after the roll, the post-roll point, and three
    mutually-relevant boolean flags describing the *kind* of event. At most one
    of ``point_established`` / ``point_made`` / ``seven_out`` is ever true; all
    three are false for a roll that leaves the phase unchanged.
    """

    #: Phase the table was in immediately BEFORE this roll.
    previous: Phase
    #: Phase the table is in immediately AFTER this roll.
    current: Phase
    #: The point value AFTER this roll -- the live point number while on POINT,
    #: or ``None`` whenever the table is (back) on come-out.
    point: int | None
    #: True iff this come-out roll established a new point.
    point_established: bool
    #: True iff this roll hit the established point (point made -> come-out).
    point_made: bool
    #: True iff this roll was a seven-out (rolled 7 while on POINT).
    seven_out: bool

    def to_dict(self) -> PhaseTransitionPayload:
        """Serialize to a UI/MC-friendly shape with phases as stable strings."""
        return {
            "previous": self.previous.value,
            "current": self.current.value,
            "point": self.point,
            "point_established": self.point_established,
            "point_made": self.point_made,
            "seven_out": self.seven_out,
        }


class GameStatePayload(TypedDict):
    """Serialized shape of a :class:`GameState`."""

    phase: str
    point: int | None


class GameState:
    """The mutable table-level come-out / point phase machine.

    Starts on the come-out with no point. :meth:`apply` advances the machine for
    one rolled total and returns a :class:`PhaseTransition` describing the event.
    See the module docstring for what is intentionally NOT modelled here (line
    bet settlement, Come/Don't-Come sub-points).
    """

    def __init__(self) -> None:
        """Begin a fresh shooter's round: come-out, no point."""
        self.phase: Phase = Phase.COME_OUT
        self.point: int | None = None

    def reset(self) -> None:
        """Return the machine to a fresh come-out with no point."""
        self.phase = Phase.COME_OUT
        self.point = None

    def apply(self, total: int) -> PhaseTransition:
        """Advance the phase machine for one rolled total; return the event.

        Mutates :attr:`phase` / :attr:`point` per the come-out/point rules and
        returns a :class:`PhaseTransition` recording the before/after phases and
        which event (if any) occurred.
        """
        # Fail-fast: an impossible total can never reach the phase logic.
        if not _MIN_TOTAL <= total <= _MAX_TOTAL:
            msg = f"total must be in {_MIN_TOTAL}..{_MAX_TOTAL}, got {total}"
            raise ValueError(msg)

        # Snapshot the pre-roll phase so the transition can report it.
        previous = self.phase

        if self.phase is Phase.COME_OUT:
            return self._apply_come_out(total, previous)
        return self._apply_point(total, previous)

    def _apply_come_out(self, total: int, previous: Phase) -> PhaseTransition:
        """Handle a roll while on the come-out."""
        if total in _POINT_NUMBERS:
            # A point number establishes the point: move to POINT phase.
            self.phase = Phase.POINT
            self.point = total
            return PhaseTransition(
                previous=previous,
                current=self.phase,
                point=self.point,
                point_established=True,
                point_made=False,
                seven_out=False,
            )
        # Otherwise the total is 2, 3, 7, 11, or 12 -- a come-out natural or
        # craps. These settle LINE BETS but do NOT change the table phase, so the
        # machine stays on come-out with no point and reports no event.
        return PhaseTransition(
            previous=previous,
            current=self.phase,
            point=self.point,
            point_established=False,
            point_made=False,
            seven_out=False,
        )

    def _apply_point(self, total: int, previous: Phase) -> PhaseTransition:
        """Handle a roll while a point is established."""
        if total == self.point:
            # Point made: the table returns to the come-out with no point. The
            # transition's post-roll point is therefore None.
            self.phase = Phase.COME_OUT
            self.point = None
            return PhaseTransition(
                previous=previous,
                current=self.phase,
                point=self.point,
                point_established=False,
                point_made=True,
                seven_out=False,
            )
        if total == _SEVEN:
            # Seven-out: the round ends, table returns to come-out, point clears.
            self.phase = Phase.COME_OUT
            self.point = None
            return PhaseTransition(
                previous=previous,
                current=self.phase,
                point=self.point,
                point_established=False,
                point_made=False,
                seven_out=True,
            )
        # Any other total leaves the point standing: no phase change, no event.
        return PhaseTransition(
            previous=previous,
            current=self.phase,
            point=self.point,
            point_established=False,
            point_made=False,
            seven_out=False,
        )

    def to_dict(self) -> GameStatePayload:
        """Serialize to a UI/MC-friendly shape with the phase as a stable string."""
        return {"phase": self.phase.value, "point": self.point}
