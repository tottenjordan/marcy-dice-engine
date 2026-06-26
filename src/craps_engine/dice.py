"""Dice sources for the craps engine: random and deterministic.

Two interchangeable dice implementations sit behind one :class:`Dice`
protocol so the rest of the engine never cares whether rolls come from a
seeded PRNG (:class:`RandomDice`) or a hand-authored script
(:class:`ScriptedDice`). The protocol keeps the simulation loop and the
edge-case tests reading from the exact same call site (``dice.roll()``).
"""

from __future__ import annotations

import random
from dataclasses import dataclass
from typing import TYPE_CHECKING, Protocol, TypedDict, runtime_checkable

if TYPE_CHECKING:
    from collections.abc import Sequence

# A standard die shows the integers 1..6 inclusive; these bounds drive the
# fail-fast validation below and the PRNG draw range.
_MIN_PIP = 1
_MAX_PIP = 6


class DiceRollPayload(TypedDict):
    """Serialized shape of a :class:`DiceRoll`.

    All three fields are plain ints so any UI / Monte-Carlo layer consumes a
    single, JSON-friendly shape. ``total`` is included (rather than recomputed
    downstream) so the serialized record is self-describing.
    """

    die1: int
    die2: int
    total: int


@dataclass(frozen=True)
class DiceRoll:
    """One immutable two-die outcome.

    Frozen so a roll is hashable and safe to share/compare by value. The two
    pips are validated at construction (fail-fast is a repo convention), which
    also makes :class:`DiceRoll` the single chokepoint where any out-of-range
    value -- random, scripted, or otherwise -- is rejected.
    """

    die1: int
    die2: int

    def __post_init__(self) -> None:
        """Reject any die outside 1..6 immediately, naming the bad value.

        Surfacing the error at construction means a bad scripted tuple or a
        misconfigured PRNG range can never silently propagate into game logic.
        """
        for die in (self.die1, self.die2):
            if not _MIN_PIP <= die <= _MAX_PIP:
                msg = f"die must be in {_MIN_PIP}..{_MAX_PIP}, got {die}"
                raise ValueError(msg)

    @property
    def total(self) -> int:
        """The combined pip count -- the value craps bets actually resolve on."""
        return self.die1 + self.die2

    def to_dict(self) -> DiceRollPayload:
        """Serialize to a UI/MC-friendly shape with the total precomputed."""
        return {"die1": self.die1, "die2": self.die2, "total": self.total}


@runtime_checkable
class Dice(Protocol):
    """A source of :class:`DiceRoll` outcomes.

    Runtime-checkable so tests can assert an implementation satisfies the
    contract via ``isinstance``. Any object exposing ``roll() -> DiceRoll``
    is a valid dice source for the engine.
    """

    def roll(self) -> DiceRoll:
        """Produce the next dice outcome."""
        ...


class RandomDice:
    """A seedable pseudo-random dice source.

    Holds its OWN :class:`random.Random` instance rather than touching the
    global ``random`` module, so simulations stay isolated and reproducible:
    constructing two ``RandomDice`` with the same seed yields the identical
    roll sequence regardless of any other RNG use in the process.
    """

    def __init__(self, seed: int | None = None) -> None:
        """Create the source, optionally seeded for reproducibility."""
        # A private generator -- never the module-global random state.
        self._rng = random.Random(seed)  # noqa: S311 (game dice, not crypto)

    def roll(self) -> DiceRoll:
        """Roll two INDEPENDENT dice via two separate ``randint`` draws."""
        # Two distinct draws so the dice are genuinely independent, not a
        # single value mirrored across both faces.
        return DiceRoll(
            self._rng.randint(_MIN_PIP, _MAX_PIP),
            self._rng.randint(_MIN_PIP, _MAX_PIP),
        )


class ScriptedDice:
    """A deterministic dice source that replays a fixed sequence.

    Feeds exact, pre-authored outcomes so edge cases (e.g. a point-then-seven
    sequence) can be tested without relying on the PRNG. Each scripted tuple is
    validated eagerly through :class:`DiceRoll`, so an out-of-range value fails
    at construction rather than mid-replay.
    """

    def __init__(self, rolls: Sequence[tuple[int, int]]) -> None:
        """Pre-build and validate every scripted roll, then queue them."""
        # Build all DiceRolls up front: this validates each tuple immediately
        # (fail-fast) and freezes the queue against later mutation of the input.
        self._queue: list[DiceRoll] = [DiceRoll(d1, d2) for d1, d2 in rolls]
        self._index = 0

    def roll(self) -> DiceRoll:
        """Return the next scripted roll; raise once the script is exhausted."""
        if self._index >= len(self._queue):
            msg = "ScriptedDice exhausted: no more scripted rolls"
            raise IndexError(msg)
        result = self._queue[self._index]
        self._index += 1
        return result
