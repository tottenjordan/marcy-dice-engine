"""Pure, HTML-free template-context builder for the HTMX browser frontend.

The HTMX routes in :mod:`craps_api.app` are deliberately thin: they resolve a
controller, call the engine, and hand a :class:`~craps_engine.play.GameView`
snapshot to :func:`build_board_context` here, which flattens it into the plain
``dict`` the ``_board.html`` partial renders. Keeping this transform pure (no
Jinja, no FastAPI, no I/O) means the whole view mapping — dollar formatting, dice
faces, the flat bet rows, the game-over banner text — is unit-testable WITHOUT
rendering HTML or booting the app, mirroring how ``craps_tui.viewmodel`` factors
pure formatting out of the Textual app.

The context is intentionally flat and JSON-primitive so the template stays a dumb
renderer: every value is a ``str``/``int``/``bool``/``None`` or a small list of
such dicts. ``session_id`` is embedded so the partial can build the per-session
HTMX action URLs (``/game/{id}/bet`` and ``/game/{id}/roll``), which is how
browser session identity travels across HTMX requests.
"""

from __future__ import annotations

from fractions import Fraction
from typing import TYPE_CHECKING, TypedDict

if TYPE_CHECKING:
    from craps_engine.money import FractionPayload
    from craps_engine.play import GameViewPayload

# Unicode die faces (1..6) indexed by pip count, so a die value maps straight to
# its glyph. Index 0 is unused (dice never show 0 pips).
_DIE_FACES = ("", "⚀", "⚁", "⚂", "⚃", "⚄", "⚅")


class BetRow(TypedDict):
    """One flattened active-bet row for the template: id, type, dollar stake, working."""

    id: str
    type: str
    amount: str
    working: bool


class OutcomeRow(TypedDict):
    """One flattened last-roll resolution row: bet id, status, signed dollar delta, note."""

    bet_id: str
    status: str
    delta: str
    note: str


class BoardContext(TypedDict):
    """The flat, primitive-only context the ``_board.html`` partial consumes.

    Every field is a ``str``/``int``/``bool``/``None`` or a list of the small
    row dicts above — no engine objects and no Fractions leak through, so the
    template is a dumb renderer over already-formatted values.
    """

    session_id: str
    starting_bankroll: str
    bankroll: str
    running_net: str
    phase: str
    point: int | None
    active_bets: list[BetRow]
    has_last_roll: bool
    die1: int
    die2: int
    die1_face: str
    die2_face: str
    total: int
    last_outcomes: list[OutcomeRow]
    rolls_used: int
    rolls_left: int
    game_over: bool
    game_over_reason: str | None
    odds_available: bool
    hint: str
    #: Optional one-line notice from the last action (e.g. a bet refusal). Empty
    #: string when there is nothing to flash, so the template can guard on it.
    flash: str


def _fraction_from_payload(payload: FractionPayload) -> Fraction:
    """Rebuild the exact :class:`Fraction` from a serialized payload's ``exact`` string.

    The ``exact`` field is ``"numerator/denominator"`` (see
    :func:`craps_engine.money.serialize_fraction`), so the value round-trips
    losslessly without ever touching the lossy ``float`` view.
    """
    num, _, denom = payload["exact"].partition("/")
    return Fraction(int(num), int(denom))


def _dollars(payload: FractionPayload) -> str:
    """Render a money payload as a clean dollar string, e.g. ``$300`` or ``$12.50``.

    Whole-dollar amounts drop the decimals (``$300``); fractional amounts show
    two decimal places (``$12.50``). Never signed — see :func:`_signed_dollars`
    for the net-change form.
    """
    value = _fraction_from_payload(payload)
    return f"${_money_body(value)}"


def _signed_dollars(payload: FractionPayload) -> str:
    """Render a money payload with an explicit sign, e.g. ``+$40``, ``-$12`` or ``$0``.

    Used for the running-net figure where the sign is the salient part.
    :class:`Fraction` has no ``:+`` spec, so the sign is built by hand from the
    magnitude (mirroring ``craps_tui.viewmodel._signed_fraction``).
    """
    value = _fraction_from_payload(payload)
    if value == 0:
        return "$0"
    sign = "-" if value < 0 else "+"
    return f"{sign}${_money_body(abs(value))}"


def _money_body(value: Fraction) -> str:
    """Format a non-negative :class:`Fraction` as ``300`` or ``12.50`` (no sign, no ``$``)."""
    if value.denominator == 1:
        return str(value.numerator)
    return f"{float(value):.2f}"


def build_board_context(
    view: GameViewPayload,
    *,
    session_id: str,
    hint: str,
    flash: str = "",
) -> BoardContext:
    """Flatten a :class:`GameViewPayload` (+ hint + session id) into template context.

    Pure and deterministic: the same inputs always yield the same flat dict. The
    caller supplies ``hint`` (from :func:`craps_engine.play.coaching_hint` on the
    live view) and the ``session_id`` so the partial can target this game's HTMX
    endpoints. Dice fields are populated from ``last_roll`` when present and left
    at safe defaults (``has_last_roll=False``) before the first roll so the
    template can guard the dice area with a single flag.

    Args:
        view: The engine's serialized game snapshot.
        session_id: The store id for this game, embedded for HTMX action URLs.
        hint: The one-line coaching hint for this moment.
        flash: An optional one-line notice from the last action (e.g. a bet
            refusal message). Defaults to empty (nothing to show).

    Returns:
        A flat, primitive-only :class:`BoardContext`.
    """
    last_roll = view["last_roll"]
    has_last_roll = last_roll is not None
    die1 = last_roll["die1"] if last_roll else 0
    die2 = last_roll["die2"] if last_roll else 0
    total = last_roll["total"] if last_roll else 0
    active_bets: list[BetRow] = [
        {
            "id": bet["id"],
            "type": bet["type"],
            "amount": _dollars(bet["amount"]),
            "working": bet["working"],
        }
        for bet in view["active_bets"]
    ]
    last_outcomes: list[OutcomeRow] = [
        {
            "bet_id": res["bet_id"],
            "status": res["status"],
            "delta": _signed_dollars(res["delta"]),
            "note": res["note"],
        }
        for res in view["last_outcomes"]
    ]
    return {
        "session_id": session_id,
        "starting_bankroll": _dollars(view["starting_bankroll"]),
        "bankroll": _dollars(view["bankroll"]),
        "running_net": _signed_dollars(view["running_net"]),
        "phase": view["phase"],
        "point": view["point"],
        "active_bets": active_bets,
        "has_last_roll": has_last_roll,
        "die1": die1,
        "die2": die2,
        "die1_face": _DIE_FACES[die1] if has_last_roll else "",
        "die2_face": _DIE_FACES[die2] if has_last_roll else "",
        "total": total,
        "last_outcomes": last_outcomes,
        "rolls_used": view["rolls_used"],
        "rolls_left": view["rolls_left"],
        "game_over": view["game_over"],
        "game_over_reason": view["game_over_reason"],
        "odds_available": view["odds_available"],
        "hint": hint,
        "flash": flash,
    }
