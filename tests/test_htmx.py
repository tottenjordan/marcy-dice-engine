"""Tests for the HTMX browser frontend (server-rendered HTML routes + board builder).

Two layers are exercised:

1. The pure :func:`craps_api.board.build_board_context` transform (payload in ->
   flat context dict out) — no HTTP, no HTML.
2. The server-rendered HTML routes via ``TestClient(create_app())``, asserting on
   rendered HTML substrings (bankroll, dice faces, hint, bet type, banners). All
   HTML tests use a fixed seed so dice/bankroll are deterministic.

Session identity travels IN THE BOARD HTML: every HTMX action URL embeds the
session id (``/game/{id}/bet``, ``/game/{id}/roll``), so the assertions here also
prove that carry-across mechanism.
"""

from __future__ import annotations

import re
from fractions import Fraction

from fastapi.testclient import TestClient
from jinja2 import Environment, FileSystemLoader, select_autoescape

from craps_api.app import _TEMPLATES_DIR, create_app
from craps_api.board import _DIE_FACES, _zone_key, build_board_context
from craps_engine.money import serialize_fraction
from craps_engine.registry import odds_ratio, odds_unit, place_unit, snap_to_odds_unit


def _render_partial(context: dict[str, object]) -> str:
    """Render the ``_board.html`` partial directly for a hand-built context.

    Lets a felt-rendering test drive the exact board state (a travelled come bet +
    come-odds) deterministically, without rolling random dice until that state
    happens to arise. Mirrors the app's Jinja2 autoescaping.
    """
    env = Environment(
        loader=FileSystemLoader(str(_TEMPLATES_DIR)),
        autoescape=select_autoescape(["html"]),
    )
    return env.get_template("_board.html").render(**context)


def _client() -> TestClient:
    """A fresh app + client with an isolated in-memory session store."""
    return TestClient(create_app())


def _money(amount: int) -> object:
    """A non-percent money payload for a whole-dollar amount (builder input)."""
    return serialize_fraction(Fraction(amount), as_percent=False)


def _amount_dollars(payload: dict) -> int:
    """Whole-dollar magnitude of a serialized money payload (via its exact ``num/den``)."""
    num, _, denom = payload["exact"].partition("/")
    return int(Fraction(int(num), int(denom)))


def _start_game(client: TestClient, **form: object) -> tuple[str, str]:
    """POST the new-game form; return ``(session_id, board_html)``."""
    resp = client.post("/game", data=form)
    assert resp.status_code == 200, resp.text
    html = resp.text
    session_id = _extract_session_id(html)
    return session_id, html


def _extract_session_id(html: str) -> str:
    """Pull the session id out of a board fragment's embedded HTMX action URLs."""
    marker = "/game/"
    start = html.index(marker) + len(marker)
    end = start
    while html[end] not in "/\"'":
        end += 1
    return html[start:end]


# --- pure builder unit tests ------------------------------------------------


def _base_payload(**overrides: object) -> dict[str, object]:
    """A minimal valid GameViewPayload for builder tests, with overrides."""
    payload: dict[str, object] = {
        "starting_bankroll": _money(300),
        "bankroll": _money(300),
        "running_net": serialize_fraction(Fraction(0), as_percent=False),
        "phase": "come_out",
        "point": None,
        "active_bets": [],
        "last_roll": None,
        "last_outcomes": [],
        "recent_rolls": [],
        "rolls_used": 0,
        "rolls_left": 100,
        "game_over": False,
        "game_over_reason": None,
        "odds_available": False,
        "variant": "standard",
        "point_numbers": [4, 5, 6, 8, 9, 10],
        "allow_dont": True,
    }
    payload.update(overrides)
    return payload


def test_builder_flattens_money_and_defaults() -> None:
    ctx = build_board_context(_base_payload(), session_id="abc", hint="hi")  # type: ignore[arg-type]
    assert ctx["session_id"] == "abc"
    assert ctx["starting_bankroll"] == "$300"
    assert ctx["bankroll"] == "$300"
    assert ctx["running_net"] == "$0"
    assert ctx["hint"] == "hi"
    assert ctx["has_last_roll"] is False
    assert ctx["die1_face"] == ""
    assert ctx["active_bets"] == []
    assert ctx["flash"] == ""


def test_builder_surfaces_flash_message() -> None:
    ctx = build_board_context(  # type: ignore[arg-type]
        _base_payload(),
        session_id="abc",
        hint="hi",
        flash="odds require an established point",
    )
    assert ctx["flash"] == "odds require an established point"


def test_builder_signed_net_and_dice_faces() -> None:
    payload = _base_payload(
        bankroll=_money(340),
        running_net=serialize_fraction(Fraction(40), as_percent=False),
        last_roll={"die1": 3, "die2": 4, "total": 7},
    )
    ctx = build_board_context(payload, session_id="x", hint="")  # type: ignore[arg-type]
    assert ctx["running_net"] == "+$40"
    assert ctx["has_last_roll"] is True
    assert ctx["die1_face"] == "⚂"
    assert ctx["die2_face"] == "⚃"
    assert ctx["total"] == 7


def test_builder_negative_net_and_bet_rows() -> None:
    payload = _base_payload(
        running_net=serialize_fraction(Fraction(-12), as_percent=False),
        active_bets=[
            {"id": "pass0", "type": "PassLine", "amount": _money(10), "working": True},
        ],
        last_outcomes=[
            {
                "bet_id": "pass0",
                "status": "win",
                "delta": serialize_fraction(Fraction(10), as_percent=False),
                "note": "natural",
            },
        ],
    )
    ctx = build_board_context(payload, session_id="x", hint="")  # type: ignore[arg-type]
    assert ctx["running_net"] == "-$12"
    assert ctx["active_bets"][0]["type"] == "PassLine"
    assert ctx["active_bets"][0]["amount"] == "$10"
    assert ctx["last_outcomes"][0]["delta"] == "+$10"


def test_builder_fractional_dollars() -> None:
    payload = _base_payload(bankroll=serialize_fraction(Fraction(25, 2), as_percent=False))
    ctx = build_board_context(payload, session_id="x", hint="")  # type: ignore[arg-type]
    assert ctx["bankroll"] == "$12.50"


# --- zone-key + chip-aggregation unit tests ---------------------------------


def _bet(bet_type: str, amount: int, **extra: object) -> dict[str, object]:
    """One active-bet payload dict shaped like an engine ``BetPayload`` + extras."""
    row: dict[str, object] = {
        "id": f"{bet_type}0",
        "type": bet_type,
        "amount": _money(amount),
        "working": True,
    }
    row.update(extra)
    return row


def test_zone_key_fixed_line_bets() -> None:
    assert _zone_key(_bet("PassLine", 10), point=None) == "pass"
    assert _zone_key(_bet("DontPass", 10), point=None) == "dontpass"


def test_zone_key_place_and_puck_odds() -> None:
    assert _zone_key(_bet("PlaceBet", 6, number=6), point=6) == "place-6"
    # Odds backing the PUCK point map to the puck take/lay slots.
    assert _zone_key(_bet("TakeOdds", 10, number=4), point=4) == "odds-4"
    assert _zone_key(_bet("LayOdds", 10, number=10), point=10) == "lay-10"


def test_zone_key_come_odds_split_from_puck_odds() -> None:
    # Odds on a come-point (≠ the puck point) get their own box-rendered zone so
    # their chip never collides with the puck-point odds slot.
    assert _zone_key(_bet("TakeOdds", 10, number=6), point=4) == "come-odds-6"
    assert _zone_key(_bet("LayOdds", 10, number=6), point=4) == "come-lay-6"
    # With no puck point (come-out) every surviving odds bet is come-odds.
    assert _zone_key(_bet("TakeOdds", 10, number=6), point=None) == "come-odds-6"


def test_zone_key_come_bets_travelling_and_established() -> None:
    assert _zone_key(_bet("ComeBet", 10, come_point=None), point=None) == "come"
    assert _zone_key(_bet("ComeBet", 10, come_point=5), point=None) == "come-5"
    assert _zone_key(_bet("DontCome", 10, come_point=None), point=None) == "dontcome"
    assert _zone_key(_bet("DontCome", 10, come_point=8), point=None) == "dontcome-8"


def test_zone_key_unknown_type_is_none() -> None:
    assert _zone_key(_bet("Fireworks", 10), point=None) is None


def test_chip_zones_aggregates_same_zone_exactly() -> None:
    payload = _base_payload(
        active_bets=[
            _bet("PlaceBet", 6, number=6),
            _bet("PlaceBet", 6, number=6),
        ],
    )
    ctx = build_board_context(payload, session_id="x", hint="")  # type: ignore[arg-type]
    assert ctx["chip_zones"] == {"place-6": "$12"}


def test_chip_zones_keeps_distinct_zones_separate() -> None:
    payload = _base_payload(
        active_bets=[
            _bet("PassLine", 10),
            _bet("PlaceBet", 6, number=6),
        ],
    )
    ctx = build_board_context(payload, session_id="x", hint="")  # type: ignore[arg-type]
    assert ctx["chip_zones"] == {"pass": "$10", "place-6": "$6"}


def test_chip_zones_empty_when_no_bets() -> None:
    ctx = build_board_context(_base_payload(), session_id="x", hint="")  # type: ignore[arg-type]
    assert ctx["chip_zones"] == {}


def test_chip_zones_skips_unknown_zone() -> None:
    payload = _base_payload(active_bets=[_bet("Fireworks", 10)])
    ctx = build_board_context(payload, session_id="x", hint="")  # type: ignore[arg-type]
    assert ctx["chip_zones"] == {}


def test_bet_rows_carry_number_and_come_point() -> None:
    payload = _base_payload(
        active_bets=[
            _bet("PlaceBet", 6, number=6),
            _bet("PassLine", 10),
            _bet("ComeBet", 10, come_point=5),
        ],
    )
    ctx = build_board_context(payload, session_id="x", hint="")  # type: ignore[arg-type]
    place_row, pass_row, come_row = ctx["active_bets"]
    assert place_row["number"] == 6
    assert place_row["come_point"] is None
    assert pass_row["number"] is None
    assert pass_row["come_point"] is None
    assert come_row["come_point"] == 5


def test_chip_zones_split_puck_odds_from_come_odds() -> None:
    """Puck-point odds and come-point odds land in distinct chip zones."""
    payload = _base_payload(
        phase="point",
        point=4,
        odds_available=True,
        active_bets=[
            _bet("TakeOdds", 10, number=4),  # backs the puck point
            _bet("TakeOdds", 10, number=6),  # backs come-point 6
        ],
    )
    ctx = build_board_context(payload, session_id="x", hint="")  # type: ignore[arg-type]
    assert ctx["chip_zones"] == {"odds-4": "$10", "come-odds-6": "$10"}


def test_bet_row_come_bet_can_add_odds_only_when_travelled() -> None:
    """A come bet exposes '+ odds' once it has a come-point and the game is live."""
    payload = _base_payload(
        phase="point",
        point=4,
        active_bets=[
            _bet("ComeBet", 10, come_point=6),
            _bet("ComeBet", 10, come_point=None),
        ],
    )
    ctx = build_board_context(payload, session_id="x", hint="")  # type: ignore[arg-type]
    travelled, coming = ctx["active_bets"]
    assert travelled["can_add_odds"] is True
    assert coming["can_add_odds"] is False


def test_bet_row_come_odds_expose_come_out_toggle() -> None:
    """Come-odds (number ≠ puck) expose the come-out on/off toggle + its state."""
    payload = _base_payload(
        phase="point",
        point=4,
        odds_available=True,
        active_bets=[
            _bet("TakeOdds", 10, number=6, come_out_working=True),  # come odds
            _bet("TakeOdds", 10, number=4),  # puck odds
        ],
    )
    ctx = build_board_context(payload, session_id="x", hint="")  # type: ignore[arg-type]
    come_odds, puck_odds = ctx["active_bets"]
    assert come_odds["can_toggle_come_out"] is True
    assert come_odds["come_out_working"] is True
    assert puck_odds["can_toggle_come_out"] is False
    assert puck_odds["come_out_working"] is False


# --- risk / history / odds-tip / row-affordance unit tests ------------------


def test_total_at_risk_sums_all_active_bets_exactly() -> None:
    payload = _base_payload(
        active_bets=[
            _bet("PlaceBet", 6, number=6),
            _bet("PlaceBet", 6, number=8),
        ],
    )
    ctx = build_board_context(payload, session_id="x", hint="")  # type: ignore[arg-type]
    assert ctx["total_at_risk"] == "$12"


def test_total_at_risk_includes_non_working_bet() -> None:
    # Under the wallet model "at risk" is every stake on the felt, so an off
    # (non-working) bet is still counted — its chips are on the table.
    payload = _base_payload(
        active_bets=[
            _bet("PlaceBet", 6, number=6),
            _bet("PlaceBet", 6, number=8, working=False),
        ],
    )
    ctx = build_board_context(payload, session_id="x", hint="")  # type: ignore[arg-type]
    assert ctx["total_at_risk"] == "$12"


def test_total_at_risk_zero_when_no_bets() -> None:
    ctx = build_board_context(_base_payload(), session_id="x", hint="")  # type: ignore[arg-type]
    assert ctx["total_at_risk"] == "$0"


def test_bet_row_live_true_for_working_bet() -> None:
    payload = _base_payload(active_bets=[_bet("PassLine", 10)])
    ctx = build_board_context(payload, session_id="x", hint="")  # type: ignore[arg-type]
    assert ctx["active_bets"][0]["live"] is True


def test_bet_row_place_live_during_point_even_when_not_working() -> None:
    # A Place bet carries working=False but is exposed to the dice during the
    # point, so its row must read live (no "(off)" marker).
    payload = _base_payload(
        phase="point",
        point=4,
        active_bets=[_bet("PlaceBet", 6, number=6, working=False)],
    )
    ctx = build_board_context(payload, session_id="x", hint="")  # type: ignore[arg-type]
    assert ctx["active_bets"][0]["live"] is True


def test_bet_row_place_off_on_come_out() -> None:
    # On the come-out a non-working Place bet is genuinely off.
    payload = _base_payload(
        phase="come_out",
        active_bets=[_bet("PlaceBet", 6, number=6, working=False)],
    )
    ctx = build_board_context(payload, session_id="x", hint="")  # type: ignore[arg-type]
    assert ctx["active_bets"][0]["live"] is False


def test_last_roll_net_signs_mixed_outcomes() -> None:
    payload = _base_payload(
        last_roll={"die1": 3, "die2": 4, "total": 7},
        last_outcomes=[
            {
                "bet_id": "a",
                "status": "win",
                "delta": serialize_fraction(Fraction(7), as_percent=False),
                "note": "",
            },
            {
                "bet_id": "b",
                "status": "lose",
                "delta": serialize_fraction(Fraction(-5), as_percent=False),
                "note": "",
            },
        ],
    )
    ctx = build_board_context(payload, session_id="x", hint="")  # type: ignore[arg-type]
    assert ctx["last_roll_net"] == "+$2"


def test_last_roll_net_empty_before_any_roll() -> None:
    ctx = build_board_context(_base_payload(), session_id="x", hint="")  # type: ignore[arg-type]
    assert ctx["last_roll_net"] == ""


def test_recent_rolls_map_faces_and_preserve_order() -> None:
    payload = _base_payload(
        recent_rolls=[
            {"die1": 5, "die2": 2, "total": 7},
            {"die1": 3, "die2": 3, "total": 6},
        ],
    )
    ctx = build_board_context(payload, session_id="x", hint="")  # type: ignore[arg-type]
    chips = ctx["recent_rolls"]
    assert len(chips) == 2
    # Newest-first order preserved (engine already ordered it).
    assert chips[0]["die1"] == 5
    assert chips[0]["die2"] == 2
    assert chips[0]["total"] == 7
    assert chips[0]["die1_face"] == _DIE_FACES[5]
    assert chips[0]["die2_face"] == _DIE_FACES[2]
    assert chips[1]["total"] == 6


def test_recent_rolls_empty_when_none() -> None:
    ctx = build_board_context(_base_payload(), session_id="x", hint="")  # type: ignore[arg-type]
    assert ctx["recent_rolls"] == []


def test_capped_false_when_uncapped() -> None:
    payload = _base_payload(rolls_left=None)
    ctx = build_board_context(payload, session_id="x", hint="")  # type: ignore[arg-type]
    assert ctx["capped"] is False
    assert ctx["rolls_left"] is None


def test_capped_true_when_capped() -> None:
    payload = _base_payload(rolls_left=50)
    ctx = build_board_context(payload, session_id="x", hint="")  # type: ignore[arg-type]
    assert ctx["capped"] is True
    assert ctx["rolls_left"] == 50


def test_zone_odds_are_exact_static_ratios() -> None:
    ctx = build_board_context(_base_payload(), session_id="x", hint="")  # type: ignore[arg-type]
    zo = ctx["zone_odds"]
    assert zo["pass"] == "1:1"  # noqa: S105 — felt zone key, not a secret
    assert zo["dontpass"] == "1:1"
    assert zo["place-6"] == "7:6"
    assert zo["place-5"] == "7:5"
    assert zo["place-4"] == "9:5"
    assert zo["odds-4"] == "2:1"
    assert zo["odds-5"] == "3:2"
    assert zo["odds-6"] == "6:5"
    assert zo["lay-4"] == "1:2"
    assert zo["lay-5"] == "2:3"
    assert zo["lay-6"] == "5:6"


def test_place_units_are_exact_static_units() -> None:
    ctx = build_board_context(_base_payload(), session_id="x", hint="")  # type: ignore[arg-type]
    pu = ctx["place_units"]
    assert pu["place-6"] == 6
    assert pu["place-8"] == 6
    assert pu["place-5"] == 5
    assert pu["place-9"] == 5
    assert pu["place-4"] == 5
    assert pu["place-10"] == 5


def test_odds_units_are_exact_static_units() -> None:
    ctx = build_board_context(_base_payload(), session_id="x", hint="")  # type: ignore[arg-type]
    ou = ctx["odds_units"]
    # Take odds: stake leg of the true odds (4/10 -> 1, 5/9 -> 2, 6/8 -> 5).
    assert ou["odds-4"] == 1
    assert ou["odds-10"] == 1
    assert ou["odds-5"] == 2
    assert ou["odds-9"] == 2
    assert ou["odds-6"] == 5
    assert ou["odds-8"] == 5
    # Lay odds: stake leg of the inverse odds (4/10 -> 2, 5/9 -> 3, 6/8 -> 6).
    assert ou["lay-4"] == 2
    assert ou["lay-10"] == 2
    assert ou["lay-5"] == 3
    assert ou["lay-9"] == 3
    assert ou["lay-6"] == 6
    assert ou["lay-8"] == 6


def test_net_pct_positive() -> None:
    payload = _base_payload(
        running_net=serialize_fraction(Fraction(40), as_percent=False),
    )
    ctx = build_board_context(payload, session_id="x", hint="")  # type: ignore[arg-type]
    assert ctx["net_pct"] == "+13.3%"


def test_net_pct_negative() -> None:
    payload = _base_payload(
        running_net=serialize_fraction(Fraction(-12), as_percent=False),
    )
    ctx = build_board_context(payload, session_id="x", hint="")  # type: ignore[arg-type]
    assert ctx["net_pct"] == "-4.0%"


def test_net_pct_zero() -> None:
    ctx = build_board_context(_base_payload(), session_id="x", hint="")  # type: ignore[arg-type]
    assert ctx["net_pct"] == "0.0%"


def test_net_pct_zero_starting_bankroll() -> None:
    payload = _base_payload(
        starting_bankroll=_money(0),
        running_net=serialize_fraction(Fraction(40), as_percent=False),
    )
    ctx = build_board_context(payload, session_id="x", hint="")  # type: ignore[arg-type]
    assert ctx["net_pct"] == ""


def test_can_remove_true_while_not_game_over() -> None:
    payload = _base_payload(active_bets=[_bet("PassLine", 10)])
    ctx = build_board_context(payload, session_id="x", hint="")  # type: ignore[arg-type]
    assert ctx["active_bets"][0]["can_remove"] is True


def test_can_remove_false_when_game_over() -> None:
    payload = _base_payload(
        active_bets=[_bet("PassLine", 10)],
        game_over=True,
        game_over_reason="bust",
    )
    ctx = build_board_context(payload, session_id="x", hint="")  # type: ignore[arg-type]
    assert ctx["active_bets"][0]["can_remove"] is False


def test_can_press_only_for_winning_bet() -> None:
    payload = _base_payload(
        active_bets=[
            _bet("PlaceBet", 12, id="place0", number=6),
            _bet("PlaceBet", 12, id="place1", number=8),
        ],
        last_roll={"die1": 3, "die2": 3, "total": 6},
        last_outcomes=[
            {
                "bet_id": "place0",
                "status": "win",
                "delta": serialize_fraction(Fraction(14), as_percent=False),
                "note": "",
            },
        ],
    )
    ctx = build_board_context(payload, session_id="x", hint="")  # type: ignore[arg-type]
    winner, other = ctx["active_bets"]
    assert winner["can_press"] is True
    assert other["can_press"] is False


def test_can_press_false_when_game_over() -> None:
    payload = _base_payload(
        active_bets=[_bet("PlaceBet", 12, number=6)],
        last_roll={"die1": 3, "die2": 3, "total": 6},
        last_outcomes=[
            {
                "bet_id": "PlaceBet0",
                "status": "win",
                "delta": serialize_fraction(Fraction(14), as_percent=False),
                "note": "",
            },
        ],
        game_over=True,
        game_over_reason="bust",
    )
    ctx = build_board_context(payload, session_id="x", hint="")  # type: ignore[arg-type]
    assert ctx["active_bets"][0]["can_press"] is False


# --- HTML route tests -------------------------------------------------------


def _establish_point_html(client: TestClient, sid: str, *, cap: int = 20) -> int:
    """Roll the HTML game until a point is on; return that point (fails otherwise)."""
    for _ in range(cap):
        html = client.post(f"/game/{sid}/roll").text
        match = re.search(r'"spec": "take (\d+)"', html)
        if match is not None:
            return int(match.group(1))
    msg = "no point established within cap"
    raise AssertionError(msg)


def _place_win_id(html: str) -> str:
    """Pull a winning place bet's id from the rendered outcomes list (fails if none).

    The board's outcomes ``<li>`` renders ``{{ res.bet_id }}: {{ res.status }}``
    as text (e.g. ``place0: win $14 — place 6 hit``), so a winning place bet's id
    is recoverable from the HTML without adding markup.
    """
    match = re.search(r"(place\d+): win", html)
    assert match is not None, "expected a winning place bet in the outcomes list"
    return match.group(1)


def test_index_returns_shell_with_form_and_htmx() -> None:
    resp = _client().get("/")
    assert resp.status_code == 200
    html = resp.text
    assert "<title" in html.lower()
    assert 'name="seed"' in html
    assert 'name="starting_bankroll"' in html
    assert "htmx" in html.lower()


def test_index_form_has_no_max_rolls_field() -> None:
    """Web games are uncapped: the new-game form no longer exposes max rolls."""
    resp = _client().get("/")
    assert resp.status_code == 200
    assert 'name="max_rolls"' not in resp.text


def test_start_game_returns_board_with_bankroll_and_hint() -> None:
    client = _client()
    _sid, html = _start_game(client, seed=1, starting_bankroll=300)
    assert "$300" in html
    # Come-out coaching hint text.
    assert "Come-out roll" in html


def test_place_bet_button_path_shows_bet() -> None:
    client = _client()
    sid, _ = _start_game(client, seed=1, starting_bankroll=300)
    resp = client.post(f"/game/{sid}/bet", data={"spec": "pass", "amount": 10})
    assert resp.status_code == 200
    # The "Your bets" list names the concrete bet type, and the pass zone's chip
    # shows the aggregated stake.
    assert "PassLine" in resp.text
    assert "$10" in resp.text


def test_place_bet_free_text_path_shows_bet() -> None:
    client = _client()
    sid, _ = _start_game(client, seed=1, starting_bankroll=300)
    resp = client.post(f"/game/{sid}/bet", data={"text": "place 6:6"})
    assert resp.status_code == 200
    # "Your bets" shows the type + box number; the place-6 chip shows $6.
    assert "PlaceBet" in resp.text
    assert "$6" in resp.text


def test_wallet_bankroll_and_net_drop_after_placing_html() -> None:
    """Wallet model: placing a bet lowers the shown bankroll and net in the HTML board."""
    client = _client()
    sid, _ = _start_game(client, seed=1, starting_bankroll=300)
    resp = client.post(f"/game/{sid}/bet", data={"spec": "pass", "amount": 10})
    assert resp.status_code == 200
    assert "$290" in resp.text
    assert "-$10" in resp.text


def test_naked_take_odds_flashed_as_refused_html() -> None:
    """Clicking Take Odds with no Pass Line bet flashes the refusal (nothing placed)."""
    client = _client()
    sid, _ = _start_game(client, seed=1, starting_bankroll=300)
    point = _establish_point_html(client, sid)
    resp = client.post(f"/game/{sid}/bet", data={"spec": f"take {point}", "amount": 10})
    assert resp.status_code == 200
    # "odds require" is unique to the flash (the felt's own "Pass Line" label would
    # otherwise match), and no bet was placed.
    assert "odds require" in resp.text
    assert "No active bets." in resp.text


def test_place_bet_during_point_not_marked_off_html() -> None:
    """A place bet resting on its point is live, so the board must not label it "(off)"."""
    client = _client()
    sid, _ = _start_game(client, seed=1, starting_bankroll=300)
    _establish_point_html(client, sid)
    resp = client.post(f"/game/{sid}/bet", data={"spec": "place 6", "amount": 6})
    assert resp.status_code == 200
    assert "PlaceBet" in resp.text
    assert "(off)" not in resp.text


def _placed_amounts(client: TestClient, sid: str) -> dict[int, int]:
    """Map each active Place bet's box number to its whole-dollar stake (via JSON)."""
    snap = client.get(f"/api/game/{sid}").json()
    return {b["number"]: _amount_dollars(b["amount"]) for b in snap["active_bets"]}


def test_place_button_snaps_stake_to_six_units_on_6_and_8() -> None:
    """A $10 felt stake on the 6 or 8 snaps up to the nearest $6 multiple ($12)."""
    client = _client()
    sid, _ = _start_game(client, seed=1, starting_bankroll=300)
    client.post(f"/game/{sid}/bet", data={"spec": "place 6", "amount": 10})
    client.post(f"/game/{sid}/bet", data={"spec": "place 8", "amount": 10})
    amounts = _placed_amounts(client, sid)
    assert amounts[6] == 12
    assert amounts[8] == 12


def test_place_button_snaps_stake_to_five_units_on_5_9_4_10() -> None:
    """A $12 felt stake on the 5/9/4/10 snaps to the nearest $5 multiple ($10)."""
    client = _client()
    sid, _ = _start_game(client, seed=1, starting_bankroll=300)
    for n in (5, 9, 4, 10):
        client.post(f"/game/{sid}/bet", data={"spec": f"place {n}", "amount": 12})
    amounts = _placed_amounts(client, sid)
    assert amounts[5] == 10
    assert amounts[9] == 10
    assert amounts[4] == 10
    assert amounts[10] == 10


def test_unparseable_place_spec_is_not_snapped_and_flashes() -> None:
    """An invalid place spec skips snapping and is flashed by the controller (no 500)."""
    client = _client()
    sid, _ = _start_game(client, seed=1, starting_bankroll=300)
    resp = client.post(f"/game/{sid}/bet", data={"spec": "place 7", "amount": 10})
    assert resp.status_code == 200
    # Nothing was placed; the refusal is surfaced rather than raising.
    assert "No active bets." in resp.text


def test_non_place_button_stake_is_not_snapped() -> None:
    """Snapping is Place/odds-only: a Pass Line stake is placed exactly as typed."""
    client = _client()
    sid, _ = _start_game(client, seed=1, starting_bankroll=300)
    client.post(f"/game/{sid}/bet", data={"spec": "pass", "amount": 13})
    snap = client.get(f"/api/game/{sid}").json()
    pass_row = next(b for b in snap["active_bets"] if b["type"] == "PassLine")
    assert _amount_dollars(pass_row["amount"]) == 13


def _odds_amount(client: TestClient, sid: str, bet_type: str) -> int:
    """Whole-dollar stake of the single active odds bet of ``bet_type`` (via JSON)."""
    snap = client.get(f"/api/game/{sid}").json()
    row = next(b for b in snap["active_bets"] if b["type"] == bet_type)
    return _amount_dollars(row["amount"])


def test_take_odds_button_snaps_stake_to_odds_unit() -> None:
    """A felt take-odds stake snaps to the point's whole-dollar odds unit.

    The Pass Line flat backing the odds is placed during the point (the engine
    permits it), so the setup is deterministic regardless of which point the seed
    establishes; the expected stake is derived from the same registry snapper.
    """
    client = _client()
    sid, _ = _start_game(client, seed=5, starting_bankroll=1000)
    point = _establish_point_html(client, sid)
    client.post(f"/game/{sid}/bet", data={"spec": "pass", "amount": 10})
    client.post(f"/game/{sid}/bet", data={"spec": f"take {point}", "amount": 7})
    placed = _odds_amount(client, sid, "TakeOdds")
    assert placed == snap_to_odds_unit(take=True, number=point, amount=7)
    assert placed % odds_unit(take=True, number=point) == 0


def test_lay_odds_button_snaps_stake_to_odds_unit() -> None:
    """A felt lay-odds stake snaps to the point's whole-dollar (inverse) odds unit."""
    client = _client()
    sid, _ = _start_game(client, seed=5, starting_bankroll=1000)
    point = _establish_point_html(client, sid)
    client.post(f"/game/{sid}/bet", data={"spec": "dontpass", "amount": 10})
    client.post(f"/game/{sid}/bet", data={"spec": f"lay {point}", "amount": 7})
    placed = _odds_amount(client, sid, "LayOdds")
    assert placed == snap_to_odds_unit(take=False, number=point, amount=7)
    assert placed % odds_unit(take=False, number=point) == 0


def test_odds_working_html_route_toggles_and_rerenders() -> None:
    """The HTMX odds-working route flips the flag and returns the board partial."""
    client = _client()
    sid, _ = _start_game(client, seed=5, starting_bankroll=1000)
    point = _establish_point_html(client, sid)
    client.post(f"/game/{sid}/bet", data={"spec": "pass", "amount": 10})
    client.post(f"/game/{sid}/bet", data={"spec": f"take {point}", "amount": 10})
    bet_id = next(
        b["id"]
        for b in client.get(f"/api/game/{sid}").json()["active_bets"]
        if b["type"] == "TakeOdds"
    )

    resp = client.post(f"/game/{sid}/odds-working", data={"bet_id": bet_id, "working": "true"})
    assert resp.status_code == 200
    assert 'id="board"' in resp.text  # a full board partial came back
    bet = next(b for b in client.get(f"/api/game/{sid}").json()["active_bets"] if b["id"] == bet_id)
    assert bet["come_out_working"] is True


def test_felt_renders_come_odds_chip_and_controls() -> None:
    """The felt shows a come-odds box chip + the +odds / come-out row controls."""
    payload = _base_payload(
        phase="point",
        point=4,
        odds_available=True,
        active_bets=[
            _bet("ComeBet", 10, come_point=6),
            _bet("TakeOdds", 10, number=6, come_out_working=False),
        ],
    )
    ctx = build_board_context(payload, session_id="s1", hint="")  # type: ignore[arg-type]
    html = _render_partial(dict(ctx))
    assert "chip-odds" in html  # come-odds chip rendered on the box
    assert "+ odds" in html  # add-odds control on the travelled come row
    assert "Come-out: OFF" in html  # come-out toggle on the come-odds row


def test_press_snaps_grown_place_stake_to_unit() -> None:
    """Pressing a Place bet snaps the grown stake to a whole unit multiple."""
    client = _client()
    sid, _ = _start_game(client, seed=5, starting_bankroll=1000)
    point = _establish_point_html(client, sid)
    client.post(f"/game/{sid}/bet", data={"spec": f"place {point}", "amount": 12})

    bet_id = ""
    for _ in range(40):
        html = client.post(f"/game/{sid}/roll").text
        if re.search(r"place\d+: win", html):
            bet_id = _place_win_id(html)
            break
    assert bet_id, "place bet never won within cap"

    client.post(f"/game/{sid}/press", data={"bet_id": bet_id})
    snap = client.get(f"/api/game/{sid}").json()
    row = next(b for b in snap["active_bets"] if b["id"] == bet_id)
    pressed = _amount_dollars(row["amount"])
    assert pressed % place_unit(point) == 0, (
        f"pressed stake {pressed} is not a whole multiple of the ${place_unit(point)} unit"
    )


def test_roll_updates_dice_and_rolls_used() -> None:
    client = _client()
    sid, _ = _start_game(client, seed=1, starting_bankroll=300)
    client.post(f"/game/{sid}/bet", data={"spec": "pass", "amount": 10})
    resp = client.post(f"/game/{sid}/roll")
    assert resp.status_code == 200
    html = resp.text
    assert "Rolls used" in html
    # A die face glyph should be present after a roll.
    assert any(face in html for face in "⚀⚁⚂⚃⚄⚅")


def test_seed_reproducibility_through_ui() -> None:
    """Two games, same seed + same roll sequence, render identical dice/bankroll."""
    client = _client()
    sid_a, _ = _start_game(client, seed=42, starting_bankroll=300)
    sid_b, _ = _start_game(client, seed=42, starting_bankroll=300)
    for sid in (sid_a, sid_b):
        client.post(f"/game/{sid}/bet", data={"spec": "pass", "amount": 10})

    frags_a: list[str] = []
    frags_b: list[str] = []
    for _ in range(8):
        frags_a.append(_board_body(client.post(f"/game/{sid_a}/roll").text))
        frags_b.append(_board_body(client.post(f"/game/{sid_b}/roll").text))
    assert frags_a == frags_b


def _board_body(html: str) -> str:
    """Strip the session id so two same-seed games compare equal on content."""
    return html.replace(_extract_session_id(html), "SID")


def test_illegal_bet_renders_refusal_not_500() -> None:
    """Take odds on the come-out is refused by the engine; surface the message.

    Submitted as a canonical ``take N`` spec directly (the Take Odds button is
    gated out of the come-out board, so we exercise the engine's odds-off-come-out
    refusal without relying on the button being present).
    """
    client = _client()
    sid, _ = _start_game(client, seed=1, starting_bankroll=300)
    resp = client.post(f"/game/{sid}/bet", data={"spec": "take 4", "amount": 10})
    assert resp.status_code == 200
    lowered = resp.text.lower()
    assert "point" in lowered or "odds" in lowered


def test_take_odds_zone_gated_on_come_out_then_appears_on_point() -> None:
    """The odds zone is absent on the come-out and present once a point is on.

    The felt only emits the Take/Lay odds zones inside ``{% if odds_available %}``
    so an empty ``take `` spec is never rendered. On the come-out no ``take``
    spec appears at all; after a point establishes the zone carries the concrete
    point number in its ``hx-vals``.
    """
    client = _client()
    sid, come_out_html = _start_game(client, seed=1, starting_bankroll=300)
    # No odds zone on the come-out: no take spec, no un-rendered template leak.
    assert '"spec": "take' not in come_out_html
    assert "take {{" not in come_out_html

    # Roll until a point is established (odds_available), then re-check. The
    # odds zone is only emitted once a point is on, so its presence is keyed on
    # the concrete ``take N`` spec appearing.
    html = come_out_html
    for _ in range(20):
        html = client.post(f"/game/{sid}/roll").text
        if '"spec": "take ' in html:
            break
    match = re.search(r'"spec": "take (\d+)"', html)
    assert match is not None, "expected an odds zone with a concrete point within 20 rolls"
    point = match.group(1)
    assert point in {"4", "5", "6", "8", "9", "10"}
    # The odds zone carries the concrete point in its hx-vals; no empty/leaked take.
    assert f'"spec": "take {point}"' in html
    assert "take {{" not in html
    assert '"spec": "take "' not in html


def test_remove_bet_drops_it_from_board() -> None:
    """Placing then removing a Pass bet takes it off the rendered board."""
    client = _client()
    sid, _ = _start_game(client, seed=1, starting_bankroll=300)
    placed = client.post(f"/game/{sid}/bet", data={"spec": "pass", "amount": 10})
    assert "PassLine" in placed.text
    # The HTML and JSON routes share ONE store, so the bet id is recoverable via
    # the JSON snapshot for this same session id (the board HTML does not embed it).
    view = client.get(f"/api/game/{sid}").json()
    bet_id = view["active_bets"][0]["id"]

    removed = client.post(f"/game/{sid}/remove", data={"bet_id": bet_id})
    assert removed.status_code == 200
    # No active bets remain: the "Your bets" list falls back to its empty state.
    assert "No active bets." in removed.text
    assert "PassLine" not in removed.text


def test_remove_unknown_bet_id_flashes_no_500() -> None:
    """An unknown bet id to /remove is handled cleanly: 200 with a flashed notice."""
    client = _client()
    sid, _ = _start_game(client, seed=1, starting_bankroll=300)
    resp = client.post(f"/game/{sid}/remove", data={"bet_id": "nope"})
    assert resp.status_code == 200
    assert "nope" in resp.text  # the refusal message names the missing id


def test_press_just_won_bet_increases_displayed_amount() -> None:
    """Pressing a Place bet right after it wins grows its displayed stake."""
    client = _client()
    sid, _ = _start_game(client, seed=5, starting_bankroll=1000)
    point = _establish_point_html(client, sid)
    client.post(f"/game/{sid}/bet", data={"spec": f"place {point}", "amount": 12})

    # Roll until the place bet wins, then capture its id from the outcomes list.
    bet_id = ""
    for _ in range(40):
        html = client.post(f"/game/{sid}/roll").text
        if re.search(r"place\d+: win", html):
            bet_id = _place_win_id(html)
            break
    assert bet_id, "place bet never won within cap"

    # A Press control must be rendered for the just-won bet before we press it.
    pre = client.get(f"/api/game/{sid}").json()
    assert any(b["id"] == bet_id for b in pre["active_bets"])
    won_board = html
    assert f'"bet_id": "{bet_id}"' in won_board
    assert "Press" in won_board

    pressed = client.post(f"/game/{sid}/press", data={"bet_id": bet_id})
    assert pressed.status_code == 200
    # The pressed bet's displayed stake is strictly larger than the original $12.
    # Read the authoritative amount back from the JSON snapshot for this same bet.
    snap = client.get(f"/api/game/{sid}").json()
    pressed_row = next(b for b in snap["active_bets"] if b["id"] == bet_id)
    pressed_amount = _amount_dollars(pressed_row["amount"])
    assert pressed_amount > 12, f"press did not grow the $12 stake: {pressed_amount}"
    # The grown stake is reflected on the rendered board.
    assert f"${pressed_amount}" in pressed.text


def test_start_game_form_is_uncapped_and_survives_many_rolls() -> None:
    """A web game (POST /game, no max_rolls) does not end by roll count."""
    client = _client()
    sid, _ = _start_game(client, seed=1, starting_bankroll=100000)
    html = ""
    for _ in range(150):
        html = client.post(f"/game/{sid}/roll").text
    assert "Game over" not in html
    # The rolls-used stat is still shown...
    assert "Rolls used" in html
    # ...but an uncapped game shows NO misleading "left" counter and never leaks
    # the raw ``None`` rolls-left figure.
    assert "left)" not in html
    assert "None" not in html


def test_game_over_banner_and_gated_controls() -> None:
    """A bust ends the (uncapped) web game: banner shown, controls gated.

    Web games are uncapped (no max_rolls form field), so game-over is driven by a
    BUST instead: a $10 pass-line bet on a $10 stake busts to $0 on a come-out
    craps loss. Seed 2's first roll is that loss, so one roll ends the game.
    """
    client = _client()
    sid, _ = _start_game(client, seed=2, starting_bankroll=10)
    client.post(f"/game/{sid}/bet", data={"spec": "pass", "amount": 10})
    resp = client.post(f"/game/{sid}/roll")
    html = resp.text
    assert "Game over" in html
    assert "bust" in html
    # Roll control must be gated once the game is over.
    assert f"/game/{sid}/roll" not in html
    # Zone buttons must be disabled once the game is over.
    assert "disabled" in html


# --- P6 felt-tracker + press/remove control render tests --------------------


def test_active_bet_renders_remove_control() -> None:
    """An active bet's row carries a Remove control that POSTs to /remove with its id."""
    client = _client()
    sid, _ = _start_game(client, seed=1, starting_bankroll=300)
    placed = client.post(f"/game/{sid}/bet", data={"spec": "pass", "amount": 10})
    bet_id = client.get(f"/api/game/{sid}").json()["active_bets"][0]["id"]
    html = placed.text
    assert f"/game/{sid}/remove" in html
    assert f'"bet_id": "{bet_id}"' in html
    assert "Remove" in html


def test_last_roll_net_indicator_shows_after_roll() -> None:
    """After a roll, the per-roll net indicator shows a signed dollar swing."""
    client = _client()
    sid, _ = _start_game(client, seed=1, starting_bankroll=300)
    client.post(f"/game/{sid}/bet", data={"spec": "pass", "amount": 10})
    html = client.post(f"/game/{sid}/roll").text
    # The dedicated net element is present, carrying a signed dollar figure.
    assert 'class="roll-net' in html
    assert re.search(r"[+\-]\$\d", html) is not None


def test_recent_rolls_strip_shows_dice_faces() -> None:
    """After several rolls, the recent-rolls strip renders dice-face glyphs."""
    client = _client()
    sid, _ = _start_game(client, seed=1, starting_bankroll=300)
    client.post(f"/game/{sid}/bet", data={"spec": "pass", "amount": 10})
    html = ""
    for _ in range(4):
        html = client.post(f"/game/{sid}/roll").text
    assert 'class="roll-strip"' in html
    assert any(face in html for face in "⚀⚁⚂⚃⚄⚅")


def test_total_at_risk_badge_present() -> None:
    """The board shows a total-at-risk figure ($0 with none, the stake once bet)."""
    client = _client()
    sid, start_html = _start_game(client, seed=1, starting_bankroll=300)
    assert "at risk" in start_html.lower()
    assert "$0" in start_html
    placed = client.post(f"/game/{sid}/bet", data={"spec": "pass", "amount": 10})
    assert "at risk" in placed.text.lower()
    assert "$10" in placed.text


def test_playable_zone_carries_pays_tooltip() -> None:
    """Playable zones fold their payout ratio into a title tooltip + aria-label.

    Line/odds/lay zones use the ratio-only pays() tooltip (Pass Line 1:1); Place
    zones now use the unit-folded place_pays() tooltip (Q3), so Place 6's ratio
    reads through the "Best in $6 units — pays 7:6" form instead of a bare "Pays".
    """
    client = _client()
    _sid, html = _start_game(client, seed=1, starting_bankroll=300)
    # Pass Line still uses the plain ratio-only tooltip.
    assert 'title="Pays 1:1"' in html
    # Place 6 pays 7:6, now folded together with its advisory $6 unit.
    assert 'title="Best in $6 units — pays 7:6"' in html
    assert "pays 7:6" in html.lower()  # folded into the place-6 aria-label too


def test_press_control_rendered_only_for_winning_bet() -> None:
    """A Press control appears once a place bet wins, POSTing to /press with its id."""
    client = _client()
    sid, _ = _start_game(client, seed=5, starting_bankroll=1000)
    point = _establish_point_html(client, sid)
    client.post(f"/game/{sid}/bet", data={"spec": f"place {point}", "amount": 12})
    html = ""
    bet_id = ""
    for _ in range(40):
        html = client.post(f"/game/{sid}/roll").text
        if re.search(r"place\d+: win", html):
            bet_id = _place_win_id(html)
            break
    assert bet_id, "place bet never won within cap"
    assert f"/game/{sid}/press" in html
    assert "Press" in html
    assert f'"bet_id": "{bet_id}"' in html


# --- felt (visual craps table) tests ----------------------------------------


def test_felt_come_out_has_all_flat_zones() -> None:
    """The come-out felt exposes every playable flat/box zone by canonical spec."""
    client = _client()
    _sid, html = _start_game(client, seed=1, starting_bankroll=300)
    for spec in (
        "place 4",
        "place 5",
        "place 6",
        "place 8",
        "place 9",
        "place 10",
        "come",
        "dontcome",
        "pass",
        "dontpass",
    ):
        assert f'"spec": "{spec}"' in html, f"missing felt zone for {spec!r}"


def test_felt_place_zone_click_renders_chip() -> None:
    """Clicking the Place-4 zone (spec/amount POST) renders a place-4 chip + bet row."""
    client = _client()
    sid, _ = _start_game(client, seed=1, starting_bankroll=300)
    resp = client.post(f"/game/{sid}/bet", data={"spec": "place 4", "amount": 10})
    assert resp.status_code == 200
    html = resp.text
    # A chip element rendered on the felt, carrying the $10 stake, plus the bet
    # named in "Your bets". (A bare "4" is not asserted — the static box row has
    # one on every board, so it would prove nothing.)
    assert 'class="chip"' in html
    assert "$10" in html
    assert "PlaceBet" in html


def test_felt_come_zone_click_places_come_bet() -> None:
    """A bare Come click (spec=come) places a come bet visible in the board."""
    client = _client()
    sid, _ = _start_game(client, seed=1, starting_bankroll=300)
    resp = client.post(f"/game/{sid}/bet", data={"spec": "come", "amount": 10})
    assert resp.status_code == 200
    html = resp.text
    assert "ComeBet" in html
    assert "$10" in html


def test_felt_has_dimmed_unsupported_decoration() -> None:
    """Unsupported classic-table areas are present but non-clickable decoration."""
    client = _client()
    _sid, html = _start_game(client, seed=1, starting_bankroll=300)
    # Dimmed decoration is marked aria-disabled and labelled (Field/Hardways).
    assert "aria-disabled" in html
    assert "Field" in html
    # The Field decoration must NOT be a clickable bet button (no hx-post on it).
    field_start = html.index("Field")
    # The enclosing element for the Field label carries no hx-post attribute.
    open_tag = html.rfind("<", 0, field_start)
    close_tag = html.index(">", field_start)
    field_block = html[open_tag:close_tag]
    assert "hx-post" not in field_block


def test_unknown_session_bet_is_404() -> None:
    resp = _client().post("/game/does-not-exist/bet", data={"spec": "pass", "amount": 10})
    assert resp.status_code == 404


def test_unknown_session_roll_is_404() -> None:
    resp = _client().post("/game/does-not-exist/roll")
    assert resp.status_code == 404


def test_empty_bet_submission_renders_refusal_not_crash() -> None:
    """A bet POST with neither a button spec nor free text is refused cleanly."""
    client = _client()
    sid, _ = _start_game(client, seed=1, starting_bankroll=300)
    resp = client.post(f"/game/{sid}/bet", data={})
    assert resp.status_code == 200
    assert "$300" in resp.text


# --- Q3 felt guidance: unit tips, point marker, net percent -----------------


def test_place_zone_tooltip_folds_advisory_unit() -> None:
    """Each Place zone's tooltip advises its optimal whole-dollar unit + payout ratio."""
    client = _client()
    _sid, html = _start_game(client, seed=1, starting_bankroll=300)
    # Place 6 pays 7:6 and is best played in $6 units; Place 4 pays 9:5 in $5 units.
    assert 'title="Best in $6 units — pays 7:6"' in html
    assert 'title="Best in $5 units — pays 9:5"' in html
    # The advisory unit is folded into the place aria-label too.
    assert "best in $6 units, pays 7:6" in html.lower()


def test_odds_zone_tooltip_folds_advisory_unit() -> None:
    """Each Take/Lay odds zone's tooltip advises its optimal odds unit + true odds.

    Mirrors the Place zone tooltip: once a point is on, the odds slots read through
    the unit-folded "Best in $N units — pays R" form. Units/ratios are derived from
    the registry so the assertion holds for whichever point the seed establishes.
    """
    client = _client()
    sid, _ = _start_game(client, seed=5, starting_bankroll=1000)
    point = _establish_point_html(client, sid)
    # Re-render the point-on board without mutating state (empty bet is a no-op).
    html = client.post(f"/game/{sid}/bet", data={}).text
    take_unit = odds_unit(take=True, number=point)
    lay_unit = odds_unit(take=False, number=point)
    take_ratio = odds_ratio(take=True, number=point)
    lay_ratio = odds_ratio(take=False, number=point)
    assert f'title="Best in ${take_unit} units — pays {take_ratio.win}:{take_ratio.stake}"' in html
    assert f'title="Best in ${lay_unit} units — pays {lay_ratio.win}:{lay_ratio.stake}"' in html


def test_felt_shows_static_unit_tip() -> None:
    """A static tip near the place row nudges players onto exact-payout units."""
    client = _client()
    _sid, html = _start_game(client, seed=1, starting_bankroll=300)
    assert 'class="felt-tip"' in html
    assert "Tip: place 6" in html


def test_point_marker_absent_on_come_out_present_on_point() -> None:
    """The ON puck + yellow ring appear only once a point is established, on that box."""
    client = _client()
    sid, come_out_html = _start_game(client, seed=1, starting_bankroll=300)
    # No point on the come-out roll: no point ring/puck yet.
    assert "zone-point" not in come_out_html

    # Roll until a point is on, capturing the very board HTML that established it.
    point = 0
    point_html = ""
    for _ in range(20):
        point_html = client.post(f"/game/{sid}/roll").text
        match = re.search(r'"spec": "take (\d+)"', point_html)
        if match is not None:
            point = int(match.group(1))
            break
    assert point, "no point established within cap"

    # The point's box carries the ring class, the ON puck text, and its aria-label.
    assert "zone-point" in point_html
    assert ">ON<" in point_html
    assert f"Point is {point}" in point_html


def test_net_percent_renders_after_resolving_roll() -> None:
    """Once the running net is non-zero, a tinted net-percent span shows beside Net."""
    client = _client()
    sid, _ = _start_game(client, seed=1, starting_bankroll=300)
    client.post(f"/game/{sid}/bet", data={"spec": "pass", "amount": 10})
    html = ""
    for _ in range(40):
        html = client.post(f"/game/{sid}/roll").text
        if "net-pct" in html or "Game over" in html:
            break
    # The net-percent badge is present and carries a "(...%)" figure.
    assert "net-pct" in html
    assert re.search(r"net-pct[^>]*>\(\S*%\)", html) is not None


# --- crapless craps variant -------------------------------------------------


def test_builder_surfaces_variant_fields() -> None:
    """The builder copies variant/point_numbers/allow_dont through to the context."""
    ctx = build_board_context(  # type: ignore[arg-type]
        _base_payload(
            variant="crapless",
            point_numbers=[2, 3, 4, 5, 6, 8, 9, 10, 11, 12],
            allow_dont=False,
        ),
        session_id="x",
        hint="",
    )
    assert ctx["variant"] == "crapless"
    assert ctx["point_numbers"] == [2, 3, 4, 5, 6, 8, 9, 10, 11, 12]
    assert ctx["allow_dont"] is False


def test_zone_odds_include_crapless_numbers() -> None:
    """The static odds/unit tables carry the crapless place + odds entries."""
    ctx = build_board_context(_base_payload(), session_id="x", hint="")  # type: ignore[arg-type]
    zo = ctx["zone_odds"]
    assert zo["place-2"] == "11:2"
    assert zo["place-12"] == "11:2"
    assert zo["place-3"] == "11:4"
    assert zo["place-11"] == "11:4"
    assert zo["odds-2"] == "6:1"
    assert zo["odds-3"] == "3:1"
    pu = ctx["place_units"]
    assert pu["place-2"] == 2
    assert pu["place-3"] == 4
    assert ctx["odds_units"]["odds-2"] == 1


def test_crapless_board_shows_extra_boxes_and_hides_dont_side() -> None:
    """A crapless board renders 2/3/11/12 boxes, omits the Don't side + badge."""
    client = _client()
    _sid, html = _start_game(client, seed=1, starting_bankroll=300, crapless="true")
    # Extra crapless box buttons exist (hx-vals for place 2/3/11/12).
    for n in (2, 3, 11, 12):
        assert f'"spec": "place {n}"' in html
    # No Don't side anywhere on the crapless felt.
    assert "Don't Come" not in html
    assert "Don't Pass Bar" not in html
    # The crapless badge + variant-aware come-out hint are present.
    assert "Crapless" in html
    assert "nothing craps out" in html


def test_standard_board_unchanged_keeps_dont_side() -> None:
    """A standard board still shows 6 boxes + the Don't side and no crapless badge."""
    client = _client()
    _sid, html = _start_game(client, seed=1, starting_bankroll=300)
    assert "Don't Come" in html
    assert "Don't Pass Bar" in html
    assert "Crapless" not in html
    # The standard-only numbers appear; the crapless-only ones do not.
    assert '"spec": "place 6"' in html
    assert '"spec": "place 2"' not in html
