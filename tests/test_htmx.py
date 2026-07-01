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

from fractions import Fraction

from fastapi.testclient import TestClient

from craps_api.app import create_app
from craps_api.board import build_board_context
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


# --- HTML route tests -------------------------------------------------------


def test_index_returns_shell_with_form_and_htmx() -> None:
    resp = _client().get("/")
    assert resp.status_code == 200
    html = resp.text
    assert "<title" in html.lower()
    assert 'name="seed"' in html
    assert 'name="starting_bankroll"' in html
    assert "htmx" in html.lower()


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
    assert "PassLine" in resp.text
    assert "$10" in resp.text


def test_place_bet_free_text_path_shows_bet() -> None:
    client = _client()
    sid, _ = _start_game(client, seed=1, starting_bankroll=300)
    resp = client.post(f"/game/{sid}/bet", data={"text": "place 6:6"})
    assert resp.status_code == 200
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


def test_take_odds_button_gated_on_come_out_then_appears_on_point() -> None:
    """The Take Odds button is absent on the come-out and present once a point is on."""
    client = _client()
    sid, come_out_html = _start_game(client, seed=1, starting_bankroll=300)
    assert "Take Odds" not in come_out_html

    # Roll until a point is established (phase leaves come-out), then re-check.
    html = come_out_html
    for _ in range(20):
        html = client.post(f"/game/{sid}/roll").text
        if "point " in html:
            break
    assert "point " in html, "expected a point to establish within 20 rolls"
    assert "Take Odds" in html
    # When present, it targets the live point number, never the empty ``take ``.
    assert 'value="take {{' not in html
    assert 'value="take "' not in html


def test_game_over_banner_and_gated_controls() -> None:
    """max_rolls=1 terminates after one roll; banner shown, controls gated."""
    client = _client()
    sid, _ = _start_game(client, seed=1, starting_bankroll=300, max_rolls=1)
    resp = client.post(f"/game/{sid}/roll")
    html = resp.text
    assert "Game over" in html
    assert "max rolls reached" in html
    # Roll control must be gated once the game is over.
    assert f"/game/{sid}/roll" not in html


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
