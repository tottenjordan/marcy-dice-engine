"""Foundational bet abstractions: the :class:`Bet` ABC and :class:`Resolution`.

Every concrete bet type (Pass Line, Place, Free Odds, ...) subclasses
:class:`Bet` and produces a :class:`Resolution` from :meth:`Bet.resolve`. The
:class:`Resolution` is the single, uniform settlement record the portfolio /
simulation layer consumes, so its ``delta`` SIGN CONVENTION (documented at
length below) is the contract every subclass MUST honor.
"""

from __future__ import annotations

import enum
from abc import ABC, abstractmethod
from dataclasses import dataclass
from fractions import Fraction
from typing import TYPE_CHECKING, TypedDict

from craps_engine.money import FractionPayload, serialize_fraction

if TYPE_CHECKING:
    from craps_engine.dice import DiceRoll
    from craps_engine.state import GameState


class ResolutionStatus(enum.Enum):
    """The qualitative outcome of resolving one bet against one roll.

    Values are stable strings so :meth:`Resolution.to_dict` can emit them
    directly and any UI / Monte-Carlo layer consumes one fixed shape.

    * ``WIN`` -- the bet won this roll.
    * ``LOSE`` -- the bet lost this roll (stake forfeited).
    * ``PUSH`` -- a stand-off: stake returned, no net change.
    * ``NO_ACTION`` -- the roll did not touch this bet (it stands unchanged).
    """

    WIN = "win"
    LOSE = "lose"
    PUSH = "push"
    NO_ACTION = "no_action"


class ResolutionPayload(TypedDict):
    """Serialized shape of a :class:`Resolution`.

    ``status`` is the stable enum string; ``delta`` is a non-percent
    :class:`~craps_engine.money.FractionPayload` (money, not a rate).
    """

    bet_id: str
    status: str
    delta: FractionPayload
    note: str


@dataclass(frozen=True)
class Resolution:
    """The immutable settlement record for ONE bet against ONE roll.

    Frozen so a settled result is a safe, hashable value to pass around and log.

    DELTA SIGN CONVENTION (the contract EVERY ``Bet.resolve`` must honor)
    -------------------------------------------------------------------
    ``delta`` is the SIGNED net change to the bankroll caused by THIS roll:

    * ``WIN``      -> ``delta = +net winnings``. This is the *winnings only*;
      it EXCLUDES the original stake, because for standing bets (Place, etc.)
      the stake stays working on the table rather than returning to the
      bankroll. Returning a come-down stake to the bankroll is the portfolio
      layer's bookkeeping (driven by ``status``), never double-counted here.
    * ``LOSE``     -> ``delta = -amount`` (the full stake is forfeited).
    * ``PUSH``     -> ``delta = 0`` (stand-off; stake returned, no net change).
    * ``NO_ACTION``-> ``delta = 0`` (the roll did not touch this bet).

    Concretely: WIN delta is non-negative, LOSE delta is non-positive, and both
    PUSH and NO_ACTION delta are exactly ``Fraction(0)``.
    """

    #: The id of the bet this resolution settles (mirrors ``Bet.id``).
    bet_id: str
    #: The qualitative outcome (see :class:`ResolutionStatus`).
    status: ResolutionStatus
    #: Signed net bankroll change for this roll -- see the SIGN CONVENTION above.
    delta: Fraction
    #: Optional human-readable note (e.g. "point made", "seven-out").
    note: str = ""

    def to_dict(self) -> ResolutionPayload:
        """Serialize to a UI/MC-friendly shape.

        ``status`` becomes its stable string; ``delta`` is serialized as MONEY
        (``as_percent=False``) so the exact/float/display payload reads as a
        plain decimal amount, not a percentage.
        """
        return {
            "bet_id": self.bet_id,
            "status": self.status.value,
            "delta": serialize_fraction(self.delta, as_percent=False),
            "note": self.note,
        }


class BetPayload(TypedDict):
    """Serialized shape of a :class:`Bet`.

    ``type`` is the concrete subclass name so a deserializer / UI can tell a
    Pass Line apart from a Place bet; ``amount`` is a non-percent money payload.
    """

    id: str
    type: str
    amount: FractionPayload
    working: bool


# A bet stake must be strictly positive; a zero/negative wager is meaningless
# and is rejected fail-fast (a repo convention) at construction.
_MIN_AMOUNT = Fraction(0)


class Bet(ABC):
    """Abstract base class for every craps bet.

    Subclasses implement :meth:`resolve` to settle the bet against a roll and
    the current table state, returning a :class:`Resolution` that obeys the
    delta SIGN CONVENTION documented on :class:`Resolution`.

    Unlike the engine's value objects, :class:`Bet` is intentionally NOT a
    frozen dataclass: concrete bets carry mutable state (notably ``working``,
    which a player can toggle off/on between rolls), so a plain class with an
    explicit ``__init__`` is the cleanest fit alongside the ABC machinery.
    """

    def __init__(
        self,
        id: str,  # noqa: A002
        amount: Fraction | int,
        *,
        working: bool = True,
    ) -> None:
        """Create a bet, validating the stake and storing it as a Fraction.

        ``amount`` accepts a :class:`~fractions.Fraction` or a plain ``int``
        (converted to an exact Fraction) for ergonomic call sites; everything
        downstream keeps exact arithmetic. A non-positive stake is rejected
        immediately, naming the offending value.
        """
        # Normalize int -> Fraction so all internal money stays exact.
        amount = Fraction(amount)
        if amount <= _MIN_AMOUNT:
            msg = f"amount must be positive, got {amount}"
            raise ValueError(msg)
        #: Stable identifier for this wager.
        self.id = id
        #: The exact stake.
        self.amount: Fraction = amount
        #: Whether the bet is live this roll; a player may turn it off/on.
        self.working = working

    @abstractmethod
    def resolve(self, roll: DiceRoll, state: GameState) -> Resolution:
        """Settle this bet against one roll and the current table state.

        Concrete subclasses MUST return a :class:`Resolution` whose ``delta``
        follows the SIGN CONVENTION on :class:`Resolution`. This method is
        abstract -- :class:`Bet` declares the contract but provides no behavior,
        so :class:`Bet` itself cannot be instantiated.
        """
        ...

    def remains_on_table(self, resolution: Resolution, roll: DiceRoll) -> bool:
        """Whether this bet stays working after ``resolution`` this roll.

        Drives the session runner's clean-up: a bet that stays on the table is
        evaluated again next roll, while a bet that comes down is removed. The
        DEFAULT rule keeps a bet up only while it is UNRESOLVED -- NO_ACTION (the
        roll didn't touch it) or PUSH (a stand-off that returns the stake intact)
        -- and takes it down on a WIN or a LOSE. Standing wagers that survive
        their own win (e.g. a Place bet) OVERRIDE this. ``roll`` is unused in the
        default (the status alone decides) but is part of the hook signature so an
        override may key on the specific total.
        """
        del roll  # The default keys only on the resolution status.
        return resolution.status in {ResolutionStatus.NO_ACTION, ResolutionStatus.PUSH}

    def advance(self, roll: DiceRoll, resolution: Resolution) -> None:
        """Apply any per-bet state transition triggered by this roll.

        Called by the session runner AFTER :meth:`resolve`, this is the single
        sanctioned place a bet may MUTATE itself in response to a roll (keeping
        :meth:`resolve` strictly pure for the portfolio's repeated EV passes). The
        DEFAULT is a no-op -- most bets carry no per-roll state -- and travelling
        bets (e.g. the Come family establishing a come-point) OVERRIDE it. Both
        ``roll`` and ``resolution`` are unused in the default but are part of the
        hook signature so an override may key on either.
        """
        del roll, resolution  # The default has no per-roll transition.

    def to_dict(self) -> BetPayload:
        """Serialize to a UI/MC-friendly shape.

        ``type`` is the concrete class name (so the wager type round-trips) and
        ``amount`` is serialized as MONEY (``as_percent=False``).
        """
        return {
            "id": self.id,
            "type": type(self).__name__,
            "amount": serialize_fraction(self.amount, as_percent=False),
            "working": self.working,
        }
