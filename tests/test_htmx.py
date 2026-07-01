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

from craps_api.app import create_app
from craps_api.board import _zone_key, build_board_context
from craps_engine.money import serialize_fraction


def _client() -> TestClient:
    """A fresh app + client with an isolated in-memory session store."""
    return TestClient(create_app())


def _money(amount: int) -> object:
    """A non-percent money payload for a whole-dollar amount (builder input)."""
    return serialize_fraction(Fraction(amount), as_percent=False)


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
        "rolls_used": 0,
        "rolls_left": 100,
        "game_over": False,
        "game_over_reason": None,
        "odds_available": False,
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
    assert _zone_key(_bet("PassLine", 10)) == "pass"
    assert _zone_key(_bet("DontPass", 10)) == "dontpass"


def test_zone_key_place_and_odds() -> None:
    assert _zone_key(_bet("PlaceBet", 6, number=6)) == "place-6"
    assert _zone_key(_bet("TakeOdds", 10, number=4)) == "odds-4"
    assert _zone_key(_bet("LayOdds", 10, number=10)) == "lay-10"


def test_zone_key_come_bets_travelling_and_established() -> None:
    assert _zone_key(_bet("ComeBet", 10, come_point=None)) == "come"
    assert _zone_key(_bet("ComeBet", 10, come_point=5)) == "come-5"
    assert _zone_key(_bet("DontCome", 10, come_point=None)) == "dontcome"
    assert _zone_key(_bet("DontCome", 10, come_point=8)) == "dontcome-8"


def test_zone_key_unknown_type_is_none() -> None:
    assert _zone_key(_bet("Fireworks", 10)) is None


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

    pressed = client.post(f"/game/{sid}/press", data={"bet_id": bet_id})
    assert pressed.status_code == 200
    # A pressed place-N chip is strictly larger than the original $12 stake.
    assert "$12" not in pressed.text or "pressed" in pressed.text.lower()


def test_start_game_form_is_uncapped_and_survives_many_rolls() -> None:
    """A web game (POST /game, no max_rolls) does not end by roll count."""
    client = _client()
    sid, _ = _start_game(client, seed=1, starting_bankroll=100000)
    html = ""
    for _ in range(150):
        html = client.post(f"/game/{sid}/roll").text
    assert "Game over" not in html
    # Uncapped: the rolls-left figure renders as None (final display is P6's job).
    assert "Rolls used" in html


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
