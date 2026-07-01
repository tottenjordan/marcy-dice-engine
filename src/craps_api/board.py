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
    from collections.abc import Callable, Mapping

    from craps_engine.bets.base import BetPayload
    from craps_engine.money import FractionPayload
    from craps_engine.play import GameViewPayload

# Unicode die faces (1..6) indexed by pip count, so a die value maps straight to
# its glyph. Index 0 is unused (dice never show 0 pips).
_DIE_FACES = ("", "⚀", "⚁", "⚂", "⚃", "⚄", "⚅")


class BetRow(TypedDict):
    """One flattened active-bet row for the template.

    Carries the ``id``, concrete bet ``type`` name, formatted dollar ``amount``
    and ``working`` flag, plus the two optional numeric qualifiers a bet can
    have: ``number`` (the box number for a Place/Odds/Lay bet) and ``come_point``
    (the travelled come-point for a Come/Don't-Come bet). Both are ``None`` for
    bets that lack them (e.g. a Pass Line row has both ``None``), letting the
    "Your bets" summary say e.g. "Place 6" without re-parsing the payload.
    """

    id: str
    type: str
    amount: str
    working: bool
    number: int | None
    come_point: int | None


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
    #: Occupied felt zone key -> its aggregated, formatted dollar label (e.g.
    #: ``{"place-6": "$12"}``). Stakes sharing a zone are SUMMED as exact
    #: :class:`Fraction` before formatting, so the chip total never drifts;
    #: unmappable bets (``_zone_key`` -> ``None``) are omitted, so a zero-bet
    #: board yields an empty dict.
    chip_zones: dict[str, str]
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


def _numbered_zone(prefix: str, bet: Mapping[str, object]) -> str:
    """Zone key for a box-numbered bet, e.g. ``place`` + number 6 -> ``place-6``."""
    return f"{prefix}-{bet['number']}"


def _come_zone(prefix: str, bet: Mapping[str, object]) -> str:
    """Zone key for a (Don't) Come bet: the flat area while travelling, else box-N.

    A ``come_point`` of ``None`` means the bet is still on the come/don't-come
    line (``come`` / ``dontcome``); once it travels to a box it becomes
    ``come-5`` / ``dontcome-8``.
    """
    come_point = bet.get("come_point")
    return prefix if come_point is None else f"{prefix}-{come_point}"


#: Concrete bet-class name -> a handler mapping that bet's payload to its felt
#: zone key. Data-driven (mirroring ``craps_engine.play._HINT_RULES``) so adding
#: a bet type is a one-line table entry, not another ``elif``. Fixed-zone line
#: bets ignore the payload; numbered/come handlers read the extra runtime fields
#: (``number`` / ``come_point``) that the base ``BetPayload`` does not declare.
_ZONE_BUILDERS: dict[str, Callable[[Mapping[str, object]], str]] = {
    "PassLine": lambda _bet: "pass",
    "DontPass": lambda _bet: "dontpass",
    "PlaceBet": lambda bet: _numbered_zone("place", bet),
    "TakeOdds": lambda bet: _numbered_zone("odds", bet),
    "LayOdds": lambda bet: _numbered_zone("lay", bet),
    "ComeBet": lambda bet: _come_zone("come", bet),
    "DontCome": lambda bet: _come_zone("dontcome", bet),
}


def _zone_key(bet: BetPayload) -> str | None:
    """Map one serialized active bet to its felt zone key, or ``None`` if unmapped.

    Dispatches on ``bet["type"]`` (the concrete bet class name) through the
    module-level :data:`_ZONE_BUILDERS` table. Numbered bets become
    ``place-6``/``odds-4``/``lay-10``; a Come/Don't-Come bet is the flat
    ``come``/``dontcome`` while travelling and ``come-5``/``dontcome-8`` once it
    has a come-point. An unknown/unexpected ``type`` returns ``None`` so such a
    bet is defensively excluded from the chip aggregation.

    The subclass-specific ``number``/``come_point`` fields are not part of the
    base ``BetPayload`` TypedDict; the handlers read them via ``Mapping`` access
    (indexing / ``.get``), which stays type-clean without ``type: ignore``.

    Args:
        bet: A serialized active-bet payload (``BetPayload`` plus any runtime
            subclass fields).

    Returns:
        The felt zone key string, or ``None`` for an unrecognized bet type.
    """
    builder = _ZONE_BUILDERS.get(bet["type"])
    if builder is None:
        return None
    return builder(bet)


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
            "number": bet.get("number"),
            "come_point": bet.get("come_point"),
        }
        for bet in view["active_bets"]
    ]
    # Sum stakes per felt zone as exact Fractions BEFORE formatting, so two $6
    # place bets read as an exact "$12" chip with no float drift; bets whose
    # zone key is None (unrecognized type) are skipped.
    zone_totals: dict[str, Fraction] = {}
    for bet in view["active_bets"]:
        key = _zone_key(bet)
        if key is None:
            continue
        zone_totals[key] = zone_totals.get(key, Fraction(0)) + _fraction_from_payload(bet["amount"])
    chip_zones: dict[str, str] = {
        key: f"${_money_body(total)}" for key, total in zone_totals.items()
    }
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
        "chip_zones": chip_zones,
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
