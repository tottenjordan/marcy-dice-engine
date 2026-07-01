"""Human bet-grammar parsing and engine-:class:`Bet` construction.

This module is the engine's single source of truth for the human-typed bet
grammar. It does two independently-testable jobs, both without any I/O:

1. **Parse** one human-typed bet string into a validated :class:`BetSpec`
   (:func:`parse_bet_spec`). Parsing is kept SEPARATE from engine-Bet
   construction so each half is independently testable.
2. **Build** the concrete engine :class:`~craps_engine.bets.base.Bet` for a
   validated spec (:func:`build_bet`).

Living in the engine (rather than the TUI view-model) lets every consumer -- the
TUI, a future web/API layer, the interactive play controller -- share ONE
grammar and ONE bet-construction path. The dependency direction is one-way
(``specs -> bets``), so the concrete bet imports live at module top-level.

Bet grammar (case-insensitive, surrounding/internal whitespace tolerant)
------------------------------------------------------------------------
Each spec is one bet on one line::

    pass:AMT            pass line
    dontpass:AMT        don't pass
    come:AMT            come (bare, still travelling)
    dontcome:AMT        don't come (bare)
    place N:AMT         place bet on box N
    take N:AMT          take odds backing point N
    lay N:AMT           lay odds backing point N

``AMT`` is a positive integer (whole dollars). ``N`` is a point/box number --
any two-die total but the 7 (standard play uses 4/5/6/8/9/10; crapless craps
also allows 2/3/11/12) -- and is REQUIRED for ``place``/``take``/``lay`` and
FORBIDDEN for the line/come bets. The grammar itself is ruleset-agnostic: it
accepts any non-7 number, and ruleset-specific legality (e.g. refusing
``place 2`` in a standard game) is enforced downstream in the
:class:`~craps_engine.play.PlayController`. The accepted separators are: a colon
``:`` before the amount, and (for the numbered bets) a space before the number,
e.g. ``place 6:6``. Whitespace around each token is ignored, so ``PLACE  8 : 6``
is also accepted.
"""

from __future__ import annotations

from dataclasses import dataclass
from fractions import Fraction
from typing import TYPE_CHECKING

from craps_engine.bets.come import ComeBet, DontCome
from craps_engine.bets.line import DontPass, PassLine
from craps_engine.bets.odds import LayOdds, TakeOdds
from craps_engine.bets.place import PlaceBet

if TYPE_CHECKING:
    from collections.abc import Callable

    from craps_engine.bets.base import Bet

# The point / box numbers a numbered bet may target. Any two-die total but the 7
# (which is never a point). Standard play uses 4/5/6/8/9/10; crapless adds
# 2/3/11/12. The grammar stays ruleset-agnostic -- per-ruleset legality is the
# PlayController's job.
_VALID_NUMBERS = frozenset({2, 3, 4, 5, 6, 8, 9, 10, 11, 12})

# Kinds that take a leading number (``kind N:AMT``); the rest are bare.
_NUMBERED_KINDS = frozenset({"place", "take", "lay"})

# All recognised bet keywords (numbered + bare line/come kinds).
_BARE_KINDS = frozenset({"pass", "dontpass", "come", "dontcome"})
_ALL_KINDS = _NUMBERED_KINDS | _BARE_KINDS

# Dispatch tables mapping a validated kind to its engine constructor. Bare kinds
# take ``(id, amount)``; numbered kinds take ``(id, number, amount)``.
_BARE_BUILDERS: dict[str, Callable[[str, Fraction], Bet]] = {
    "pass": PassLine,
    "dontpass": DontPass,
    "come": ComeBet,
    "dontcome": DontCome,
}
_NUMBERED_BUILDERS: dict[str, Callable[[str, int, Fraction], Bet]] = {
    "place": PlaceBet,
    "take": TakeOdds,
    "lay": LayOdds,
}


@dataclass(frozen=True)
class BetSpec:
    """A parsed, validated bet specification (not yet an engine :class:`Bet`).

    Keeping this distinct from the concrete engine bet lets the parser be tested
    without constructing real bets, and lets the engine-construction step be
    tested with hand-built specs.

    ``number`` is the targeted point/box for ``place``/``take``/``lay`` and is
    ``None`` for the bare line/come kinds.
    """

    #: The bet keyword, e.g. ``"pass"``, ``"place"``, ``"take"``.
    kind: str
    #: The whole-dollar stake (always a positive int).
    amount: int
    #: The point/box number for numbered bets, else ``None``.
    number: int | None = None


def parse_bet_spec(spec: str) -> BetSpec:
    """Parse ONE human bet string into a validated :class:`BetSpec`.

    See the module docstring for the full grammar. Parsing is case-insensitive
    and tolerant of surrounding/internal whitespace. Raises :class:`ValueError`
    with a clear, specific message on any malformed input: an unknown keyword, a
    missing/non-positive/non-integer amount, a numbered bet without a valid
    number, or a number supplied to a bare line/come bet.
    """
    raw = spec.strip()
    if ":" not in raw:
        msg = f"cannot parse bet spec {spec!r}: expected '<kind>[ N]:<amount>'"
        raise ValueError(msg)

    # Split once on the colon: left holds the kind (and optional number), right
    # holds the amount.
    head, _, tail = raw.partition(":")
    amount = _parse_amount(tail, spec)
    kind, number = _parse_kind_and_number(head, spec)

    if kind in _NUMBERED_KINDS:
        if number is None:
            msg = f"{kind!r} requires a point/box number (any total but 7), got {spec!r}"
            raise ValueError(msg)
        if number not in _VALID_NUMBERS:
            msg = f"{number} is not a valid point/box number (7 is never a point) in {spec!r}"
            raise ValueError(msg)
    elif number is not None:
        msg = f"{kind!r} does not take a number, but got {number} in {spec!r}"
        raise ValueError(msg)

    return BetSpec(kind=kind, amount=amount, number=number)


def _parse_amount(tail: str, spec: str) -> int:
    """Parse the post-colon amount as a strictly positive integer."""
    token = tail.strip()
    try:
        amount = int(token)
    except ValueError:
        msg = f"amount must be a positive integer, got {token!r} in {spec!r}"
        raise ValueError(msg) from None
    if amount <= 0:
        msg = f"amount must be positive, got {amount} in {spec!r}"
        raise ValueError(msg)
    return amount


def _parse_kind_and_number(head: str, spec: str) -> tuple[str, int | None]:
    """Parse the pre-colon ``<kind>[ N]`` half into a kind and optional number.

    The kind is lower-cased; an optional second whitespace-separated token is the
    numeric target. Raises on an empty/unknown kind or a non-integer number.
    """
    tokens = head.split()
    if not tokens:
        msg = f"missing bet kind in {spec!r}"
        raise ValueError(msg)

    kind = tokens[0].lower()
    if kind not in _ALL_KINDS:
        msg = f"unknown bet kind {kind!r} in {spec!r}; expected one of {sorted(_ALL_KINDS)}"
        raise ValueError(msg)

    if len(tokens) == 1:
        return kind, None
    if len(tokens) > 2:  # noqa: PLR2004 (kind + single number is the only shape)
        msg = f"too many tokens before ':' in {spec!r}"
        raise ValueError(msg)

    try:
        number = int(tokens[1])
    except ValueError:
        msg = f"number must be an integer, got {tokens[1]!r} in {spec!r}"
        raise ValueError(msg) from None
    return kind, number


def build_bet(spec: BetSpec, bet_id: str) -> Bet:
    """Construct the concrete engine :class:`Bet` for one :class:`BetSpec`.

    The caller supplies the stable ``bet_id`` (so id generation is an
    application concern, not a parsing one). The bare line/come kinds take only
    ``(id, amount)``; the numbered kinds (place/take/lay) take
    ``(id, number, amount)``. Place bets keep the engine default
    ``working=False`` (OFF on the come-out, live during a point regardless). The
    parser has already validated the kind and (for numbered bets) the number, so
    no fallthrough error path is reachable here.
    """
    amount = Fraction(spec.amount)

    if spec.kind in _BARE_KINDS:
        return _BARE_BUILDERS[spec.kind](bet_id, amount)

    # The remaining kinds are numbered; the parser guarantees a valid number.
    number = spec.number
    if number is None:  # pragma: no cover - defended by parse_bet_spec
        msg = f"{spec.kind!r} requires a number"
        raise ValueError(msg)
    return _NUMBERED_BUILDERS[spec.kind](bet_id, number, amount)
