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

from craps_engine.registry import REGISTRY, odds_ratio, place_spec, place_unit

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping

    from craps_engine.bets.base import BetPayload
    from craps_engine.money import FractionPayload, RatioOdds
    from craps_engine.play import GameViewPayload

# Unicode die faces (1..6) indexed by pip count, so a die value maps straight to
# its glyph. Index 0 is unused (dice never show 0 pips).
_DIE_FACES = ("", "⚀", "⚁", "⚂", "⚃", "⚄", "⚅")

# The box numbers a Place / Free-Odds / Lay bet can sit on. Iterated once at
# import to build the static odds-tip table below.
_POINT_NUMBERS: tuple[int, ...] = (4, 5, 6, 8, 9, 10)


def _ratio_label(ratio: RatioOdds) -> str:
    """Render a :class:`RatioOdds` as its canonical ``win:stake`` tip label (e.g. ``7:6``)."""
    return f"{ratio.win}:{ratio.stake}"


def _build_zone_odds() -> dict[str, str]:
    """Precompute every felt zone's static payout-ratio tooltip label.

    The payout ratio for a zone (Pass 1:1, Place 6 → 7:6, take-odds 4 → 2:1,
    lay-odds 4 → 1:2) is FIXED craps math — it never depends on the live
    :class:`GameViewPayload`. So it is computed ONCE at import straight from
    :mod:`craps_engine.registry` (the single source of truth for exact odds) and
    reused unchanged on every :func:`build_board_context` call, rather than
    recomputed per request. Keys mirror the :data:`_ZONE_BUILDERS` zone keys so a
    tooltip lines up with the chip zone it annotates.

    Returns:
        Zone key (``pass``/``dontpass``/``place-N``/``odds-N``/``lay-N``) -> its
        ``win:stake`` ratio label.
    """
    zone_odds: dict[str, str] = {
        "pass": _ratio_label(REGISTRY["pass_line"].payout),
        "dontpass": _ratio_label(REGISTRY["dont_pass"].payout),
    }
    for number in _POINT_NUMBERS:
        zone_odds[f"place-{number}"] = _ratio_label(place_spec(number).payout)
        zone_odds[f"odds-{number}"] = _ratio_label(odds_ratio(take=True, number=number))
        zone_odds[f"lay-{number}"] = _ratio_label(odds_ratio(take=False, number=number))
    return zone_odds


#: Static felt zone -> payout-ratio tooltip label, computed once at import from
#: the exact registry odds. Returned as-is from every :func:`build_board_context`
#: call because the ratios are immutable craps math, not per-view state.
_ZONE_ODDS: dict[str, str] = _build_zone_odds()


def _build_place_units() -> dict[str, int]:
    """Precompute every Place zone's advisory whole-dollar unit.

    The optimal Place-bet unit for a box number ($6 on the 6/8, $5 on the
    5/9 and 4/10) is FIXED craps math straight from the payout ratio's stake
    leg — see :func:`craps_engine.registry.place_unit`. Like :data:`_ZONE_ODDS`
    it never depends on the live :class:`GameViewPayload`, so it is computed
    ONCE at import from the single source of truth and reused unchanged on every
    :func:`build_board_context` call rather than recomputed per request. Keys
    mirror the ``place-N`` zone keys so a unit lines up with the felt zone it
    advises (letting the Q3 template nudge players onto efficient stakes).

    Returns:
        Zone key ``place-N`` -> its optimal whole-dollar Place unit.
    """
    return {f"place-{number}": place_unit(number) for number in _POINT_NUMBERS}


#: Static Place zone -> advisory whole-dollar unit, computed once at import from
#: the exact registry payout ratios. Returned as-is from every
#: :func:`build_board_context` call because the units are immutable craps math,
#: not per-view state.
_PLACE_UNITS: dict[str, int] = _build_place_units()


class RollChip(TypedDict):
    """One entry in the recent-roll history strip.

    A tiny, primitive-only projection of a
    :class:`~craps_engine.dice.DiceRollPayload` so the felt can render a compact
    history of the last few rolls (newest-first) as dice glyphs without touching
    the engine's roll objects. ``die1``/``die2``/``total`` are the raw pip counts
    and their sum; ``die1_face``/``die2_face`` are the matching Unicode glyphs
    (via :data:`_DIE_FACES`) so the template stays a dumb renderer.
    """

    #: First die's pip count (1..6).
    die1: int
    #: Second die's pip count (1..6).
    die2: int
    #: The rolled total (``die1 + die2``), precomputed so the template needn't add.
    total: int
    #: First die's Unicode face glyph (``_DIE_FACES[die1]``).
    die1_face: str
    #: Second die's Unicode face glyph (``_DIE_FACES[die2]``).
    die2_face: str


class BetRow(TypedDict):
    """One flattened active-bet row for the template.

    Carries the ``id``, concrete bet ``type`` name, formatted dollar ``amount``
    and ``working`` flag, plus the two optional numeric qualifiers a bet can
    have: ``number`` (the box number for a Place/Odds/Lay bet) and ``come_point``
    (the travelled come-point for a Come/Don't-Come bet). Both are ``None`` for
    bets that lack them (e.g. a Pass Line row has both ``None``), letting the
    "Your bets" summary say e.g. "Place 6" without re-parsing the payload.

    ``can_remove`` / ``can_press`` are per-row affordance flags the template uses
    to gate the take-down and press-it buttons: a bet can be removed while the
    game is live, and pressed only right after it wins (its stake is available to
    grow from fresh winnings). Both go ``False`` once the game is over.
    """

    id: str
    type: str
    amount: str
    working: bool
    number: int | None
    come_point: int | None
    #: Whether a "take it down" control should be offered for this row (the game
    #: is not over). Identical across rows on any given board.
    can_remove: bool
    #: Whether a "press it" control should be offered: this bet just WON on the
    #: last roll (its id has a ``"win"`` resolution in ``last_outcomes``) and the
    #: game is still live.
    can_press: bool


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
    #: Signed percent change of the running net vs the starting bankroll (one
    #: decimal, e.g. ``+13.3%`` / ``-4.0%`` / ``0.0%``). Empty string ``""`` when
    #: the starting bankroll is non-positive (guards div-by-zero), so the template
    #: can guard on it.
    net_pct: str
    phase: str
    point: int | None
    active_bets: list[BetRow]
    #: Occupied felt zone key -> its aggregated, formatted dollar label (e.g.
    #: ``{"place-6": "$12"}``). Stakes sharing a zone are SUMMED as exact
    #: :class:`Fraction` before formatting, so the chip total never drifts;
    #: unmappable bets (``_zone_key`` -> ``None``) are omitted, so a zero-bet
    #: board yields an empty dict.
    chip_zones: dict[str, str]
    #: Static felt zone -> payout-ratio tooltip label (e.g. ``{"place-6": "7:6"}``).
    #: The same immutable :data:`_ZONE_ODDS` table every call — the ratios are
    #: fixed craps math, not per-view state.
    zone_odds: dict[str, str]
    #: Static Place zone -> advisory whole-dollar unit (e.g. ``{"place-6": 6}``).
    #: The same immutable :data:`_PLACE_UNITS` table every call — the units are
    #: fixed craps math (the payout ratio's stake leg), not per-view state.
    place_units: dict[str, int]
    #: Summed dollar stake of the WORKING active bets — the money currently
    #: exposed to the dice. Summed as exact :class:`Fraction` before formatting;
    #: non-working bets are excluded; ``"$0"`` when nothing is at risk.
    total_at_risk: str
    #: Signed dollar swing from the last roll (``Σ delta`` over ``last_outcomes``),
    #: e.g. ``+$7`` / ``-$12`` / ``$0``. Empty string ``""`` before any roll (no
    #: last roll), so the template can guard on it.
    last_roll_net: str
    #: The last few rolls as dice-glyph chips, newest-first (already ordered and
    #: capped by the engine). Empty before the first roll.
    recent_rolls: list[RollChip]
    has_last_roll: bool
    die1: int
    die2: int
    die1_face: str
    die2_face: str
    total: int
    last_outcomes: list[OutcomeRow]
    rolls_used: int
    #: Rolls remaining before the max-rolls cap, or ``None`` when uncapped
    #: (interactive play with ``max_rolls=None``).
    rolls_left: int | None
    #: Whether the game has a max-rolls cap (``rolls_left is not None``). Lets the
    #: template hide the "rolls left" stat entirely for uncapped interactive play.
    capped: bool
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


def _signed_dollars_from_fraction(value: Fraction) -> str:
    """Render an exact :class:`Fraction` with an explicit sign, e.g. ``+$40``/``-$12``/``$0``.

    :class:`Fraction` has no ``:+`` format spec, so the sign is built by hand from
    the magnitude (mirroring ``craps_tui.viewmodel._signed_fraction``). Factored
    out of :func:`_signed_dollars` so callers holding a summed raw ``Fraction``
    (e.g. the last-roll net) format it the SAME exact way as a payload-sourced one
    without round-tripping through a serialized payload.
    """
    if value == 0:
        return "$0"
    sign = "-" if value < 0 else "+"
    return f"{sign}${_money_body(abs(value))}"


def _signed_percent(value: Fraction) -> str:
    """Render an exact ratio :class:`Fraction` as a signed one-decimal percent.

    Used for the running-net-vs-starting-bankroll figure, where the sign and
    magnitude of the swing are the salient part (``+13.3%`` / ``-4.0%``). The
    ratio is computed exactly as a :class:`Fraction` by the caller so no float
    drift enters the percentage; the lossy ``float`` conversion is deferred to
    the FINAL format step here (the display boundary), mirroring how
    :func:`_money_body` only floats at the end.

    Sign handling mirrors :func:`_signed_dollars_from_fraction`: zero renders
    WITHOUT a sign (``"0.0%"``), and the ``+``/``-`` is built by hand from the
    magnitude because :class:`Fraction` has no ``:+`` format spec.
    """
    if value == 0:
        return "0.0%"
    sign = "-" if value < 0 else "+"
    return f"{sign}{float(abs(value)) * 100:.1f}%"


def _signed_dollars(payload: FractionPayload) -> str:
    """Render a money payload with an explicit sign, e.g. ``+$40``, ``-$12`` or ``$0``.

    Used for the running-net figure where the sign is the salient part. Delegates
    to :func:`_signed_dollars_from_fraction` after rebuilding the exact value.
    """
    return _signed_dollars_from_fraction(_fraction_from_payload(payload))


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


def _bet_ids_with_win(view: GameViewPayload) -> set[str]:
    """Collect the ids of bets that WON on the last roll.

    Scans ``last_outcomes`` for resolutions whose ``status`` is the serialized win
    string ``"win"`` (the lowercase enum value) and returns their ``bet_id``s.
    Computed ONCE per board so each :class:`BetRow` decides its ``can_press`` flag
    by a cheap set-membership test instead of re-scanning the outcomes per row.
    A bet is pressable only right after it wins, so this set is the pressable
    universe for this moment (the game-over gate is applied per row on top of it).
    """
    return {res["bet_id"] for res in view["last_outcomes"] if res["status"] == "win"}


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
    game_over = view["game_over"]
    # A bet is removable while the game is live; pressable only if it just won and
    # the game is still live. Precompute the winning-id set once for the rows.
    can_remove = not game_over
    winning_ids = _bet_ids_with_win(view)
    active_bets: list[BetRow] = [
        {
            "id": bet["id"],
            "type": bet["type"],
            "amount": _dollars(bet["amount"]),
            "working": bet["working"],
            "number": bet.get("number"),
            "come_point": bet.get("come_point"),
            "can_remove": can_remove,
            "can_press": not game_over and bet["id"] in winning_ids,
        }
        for bet in view["active_bets"]
    ]
    # Money currently exposed to the dice: sum the WORKING bets' stakes as exact
    # Fractions before formatting so the total never drifts (``$0`` when none).
    risk_total = sum(
        (_fraction_from_payload(bet["amount"]) for bet in view["active_bets"] if bet["working"]),
        Fraction(0),
    )
    total_at_risk = f"${_money_body(risk_total)}"
    # Signed net swing from the last roll: Σ delta over the resolutions, summed as
    # exact Fractions. Empty string before any roll so the template can hide it.
    if has_last_roll:
        net_total = sum(
            (_fraction_from_payload(res["delta"]) for res in view["last_outcomes"]),
            Fraction(0),
        )
        last_roll_net = _signed_dollars_from_fraction(net_total)
    else:
        last_roll_net = ""
    # Newest-first roll chips: the engine already ordered and capped recent_rolls,
    # so just project each raw roll into a glyph-carrying RollChip.
    recent_rolls: list[RollChip] = [
        {
            "die1": roll["die1"],
            "die2": roll["die2"],
            "total": roll["total"],
            "die1_face": _DIE_FACES[roll["die1"]],
            "die2_face": _DIE_FACES[roll["die2"]],
        }
        for roll in view["recent_rolls"]
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
    # Running net as a signed percentage of the starting bankroll, computed from
    # the EXACT serialized Fractions (not the pre-formatted dollar strings) so the
    # ratio stays lossless until _signed_percent floats it at the display edge.
    # Guard div-by-zero: a non-positive starting bankroll yields "" (the template
    # then hides the badge) rather than raising.
    running_net = _fraction_from_payload(view["running_net"])
    starting_bankroll = _fraction_from_payload(view["starting_bankroll"])
    net_pct = "" if starting_bankroll <= 0 else _signed_percent(running_net / starting_bankroll)
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
        "net_pct": net_pct,
        "phase": view["phase"],
        "point": view["point"],
        "active_bets": active_bets,
        "chip_zones": chip_zones,
        "zone_odds": _ZONE_ODDS,
        "place_units": _PLACE_UNITS,
        "total_at_risk": total_at_risk,
        "last_roll_net": last_roll_net,
        "recent_rolls": recent_rolls,
        "has_last_roll": has_last_roll,
        "die1": die1,
        "die2": die2,
        "die1_face": _DIE_FACES[die1] if has_last_roll else "",
        "die2_face": _DIE_FACES[die2] if has_last_roll else "",
        "total": total,
        "last_outcomes": last_outcomes,
        "rolls_used": view["rolls_used"],
        "rolls_left": view["rolls_left"],
        "capped": view["rolls_left"] is not None,
        "game_over": game_over,
        "game_over_reason": view["game_over_reason"],
        "odds_available": view["odds_available"],
        "hint": hint,
        "flash": flash,
    }
