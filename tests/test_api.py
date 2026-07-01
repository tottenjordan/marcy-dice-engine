"""HTTP-level tests for the craps_api FastAPI JSON backend.

These exercise ``create_app`` through a ``TestClient`` (no live server), asserting
the JSON contract of every endpoint: the full play flow, free-text betting, seed
reproducibility over HTTP, the illegal-vs-malformed distinction, unknown-session
404s, session isolation, and surfaced game-over termination.
"""

from __future__ import annotations

from fractions import Fraction
from typing import TYPE_CHECKING

from fastapi.testclient import TestClient

from craps_api.app import create_app

if TYPE_CHECKING:
    from craps_engine.play import GameViewPayload


def _client() -> TestClient:
    """A fresh app + client with an isolated (module-fresh) session store."""
    return TestClient(create_app())


def _new_game(client: TestClient, **body: object) -> tuple[str, GameViewPayload]:
    """POST /api/game and return ``(session_id, view)``."""
    resp = client.post("/api/game", json=body)
    assert resp.status_code == 201, resp.text
    data = resp.json()
    return data["session_id"], data["view"]


def _establish_point(client: TestClient, session_id: str, *, cap: int = 20) -> int:
    """Roll until a point is on; return that point number (fails if none in ``cap``)."""
    for _ in range(cap):
        view = client.post(f"/api/game/{session_id}/roll").json()["view"]
        if view["point"] is not None:
            point = view["point"]
            assert isinstance(point, int)
            return point
    msg = "no point established within cap"
    raise AssertionError(msg)


def _roll_until_place_win(
    client: TestClient, session_id: str, bet_id: str, *, cap: int = 40
) -> GameViewPayload:
    """Roll until ``bet_id`` wins on a roll; return that winning view (fails otherwise).

    A Place bet is a STANDING wager that survives its own win, so after it wins it
    is still live and immediately pressable — the natural vehicle for a
    deterministic press test through the API.
    """
    for _ in range(cap):
        view: GameViewPayload = client.post(f"/api/game/{session_id}/roll").json()["view"]
        if view["game_over"]:
            break
        won = any(
            outcome["bet_id"] == bet_id and outcome["status"] == "win"
            for outcome in view["last_outcomes"]
        )
        if won:
            return view
    msg = f"bet {bet_id!r} did not win within cap"
    raise AssertionError(msg)


def test_new_game_returns_session_and_come_out_view() -> None:
    client = _client()
    session_id, view = _new_game(client, starting_bankroll=300, max_rolls=100)
    assert session_id
    assert view["phase"] == "come_out"
    assert view["point"] is None
    assert view["rolls_used"] == 0
    assert view["bankroll"]["exact"] == "300/1"
    assert view["active_bets"] == []
    assert view["game_over"] is False


def test_new_game_is_uncapped_by_default() -> None:
    """A game created without max_rolls is uncapped: rolls_left is None."""
    client = _client()
    _sid, view = _new_game(client)
    assert view["rolls_left"] is None


def test_wallet_bankroll_reflects_placed_stake() -> None:
    """Wallet model: placing lowers bankroll/net by the stake; removing restores it."""
    client = _client()
    session_id, _ = _new_game(client, seed=1, starting_bankroll=300)
    placed = client.post(
        f"/api/game/{session_id}/bet",
        json={"kind": "pass", "amount": 10},
    ).json()
    assert placed["view"]["bankroll"]["exact"] == "290/1"
    assert placed["view"]["running_net"]["exact"] == "-10/1"
    bet_id = placed["view"]["active_bets"][0]["id"]

    removed = client.post(f"/api/game/{session_id}/bet/{bet_id}/remove").json()
    assert removed["view"]["bankroll"]["exact"] == "300/1"
    assert removed["view"]["running_net"]["exact"] == "0/1"


def test_remove_bet_drops_it_from_active_bets() -> None:
    client = _client()
    session_id, _ = _new_game(client, seed=1)
    bet = client.post(
        f"/api/game/{session_id}/bet",
        json={"kind": "pass", "amount": 10},
    ).json()
    assert bet["ok"] is True
    bet_id = bet["view"]["active_bets"][0]["id"]

    removed = client.post(f"/api/game/{session_id}/bet/{bet_id}/remove")
    assert removed.status_code == 200
    data = removed.json()
    assert data["ok"] is True
    ids = [b["id"] for b in data["view"]["active_bets"]]
    assert bet_id not in ids


def test_remove_unknown_bet_id_is_200_ok_false() -> None:
    """An unknown BET id is handled by the controller (200, ok=false), not a 404."""
    client = _client()
    session_id, _ = _new_game(client, seed=1)
    resp = client.post(f"/api/game/{session_id}/bet/nope/remove")
    assert resp.status_code == 200
    assert resp.json()["ok"] is False


def test_remove_on_unknown_session_is_404() -> None:
    """Only an unknown SESSION is a 404 (an unknown bet id is 200/ok=false)."""
    client = _client()
    resp = client.post("/api/game/does-not-exist/bet/nope/remove")
    assert resp.status_code == 404


def test_press_after_win_grows_amount() -> None:
    """Pressing a Place bet right after its winning roll increases its amount."""
    client = _client()
    session_id, _ = _new_game(client, seed=5, starting_bankroll=1000)
    point = _establish_point(client, session_id)

    placed = client.post(
        f"/api/game/{session_id}/bet",
        json={"kind": "place", "number": point, "amount": 12},
    ).json()
    assert placed["ok"] is True
    bet_id = placed["view"]["active_bets"][0]["id"]

    won_view = _roll_until_place_win(client, session_id, bet_id)
    amount_before = next(b["amount"]["exact"] for b in won_view["active_bets"] if b["id"] == bet_id)

    pressed = client.post(f"/api/game/{session_id}/bet/{bet_id}/press")
    assert pressed.status_code == 200
    data = pressed.json()
    assert data["ok"] is True
    amount_after = next(
        b["amount"]["exact"] for b in data["view"]["active_bets"] if b["id"] == bet_id
    )
    assert Fraction(amount_after) > Fraction(amount_before)


def test_press_with_nothing_won_is_200_ok_false() -> None:
    """Pressing a bet that did not just win is refused (200, ok=false)."""
    client = _client()
    session_id, _ = _new_game(client, seed=1)
    bet = client.post(
        f"/api/game/{session_id}/bet",
        json={"kind": "pass", "amount": 10},
    ).json()
    bet_id = bet["view"]["active_bets"][0]["id"]

    resp = client.post(f"/api/game/{session_id}/bet/{bet_id}/press")
    assert resp.status_code == 200
    assert resp.json()["ok"] is False


def test_press_on_unknown_session_is_404() -> None:
    client = _client()
    resp = client.post("/api/game/does-not-exist/bet/nope/press")
    assert resp.status_code == 404


def test_uncapped_game_never_ends_by_roll_count() -> None:
    """Many rolls on an uncapped game with a big bankroll never trigger game_over."""
    client = _client()
    session_id, _ = _new_game(client, seed=1, starting_bankroll=100_000)
    last = None
    for _ in range(150):
        last = client.post(f"/api/game/{session_id}/roll").json()["view"]
    assert last is not None
    assert last["rolls_used"] == 150
    assert last["rolls_left"] is None
    assert last["game_over"] is False


def test_full_flow_structured_bet_then_roll() -> None:
    client = _client()
    session_id, _ = _new_game(client, seed=1, starting_bankroll=300, max_rolls=100)

    bet_resp = client.post(
        f"/api/game/{session_id}/bet",
        json={"kind": "pass", "amount": 10},
    )
    assert bet_resp.status_code == 200
    bet_data = bet_resp.json()
    assert bet_data["ok"] is True
    assert len(bet_data["view"]["active_bets"]) == 1

    roll_resp = client.post(f"/api/game/{session_id}/roll")
    assert roll_resp.status_code == 200
    roll_data = roll_resp.json()
    assert roll_data["ok"] is True
    assert roll_data["view"]["rolls_used"] == 1
    assert roll_data["view"]["last_roll"] is not None


def test_get_game_returns_current_view() -> None:
    client = _client()
    session_id, _ = _new_game(client, seed=1)
    resp = client.get(f"/api/game/{session_id}")
    assert resp.status_code == 200
    assert resp.json()["rolls_used"] == 0


def test_free_text_bet_matches_structured() -> None:
    client = _client()
    session_id, _ = _new_game(client, seed=1)
    resp = client.post(
        f"/api/game/{session_id}/bet",
        json={"text": "place 6:6"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["ok"] is True
    assert len(data["view"]["active_bets"]) == 1


def test_seed_reproducibility_over_http() -> None:
    """Two games with the same seed + same rolls have identical trajectories."""
    client = _client()
    session_a, _ = _new_game(client, seed=42, starting_bankroll=300, max_rolls=100)
    session_b, _ = _new_game(client, seed=42, starting_bankroll=300, max_rolls=100)

    for sid in (session_a, session_b):
        client.post(f"/api/game/{sid}/bet", json={"kind": "pass", "amount": 10})

    traj_a: list[tuple[int, str]] = []
    traj_b: list[tuple[int, str]] = []
    for _ in range(10):
        ra = client.post(f"/api/game/{session_a}/roll").json()
        rb = client.post(f"/api/game/{session_b}/roll").json()
        traj_a.append((ra["view"]["last_roll"]["total"], ra["view"]["bankroll"]["exact"]))
        traj_b.append((rb["view"]["last_roll"]["total"], rb["view"]["bankroll"]["exact"]))

    assert traj_a == traj_b


def test_different_seeds_diverge() -> None:
    """A sanity check that the seed actually drives the RNG (not a constant)."""
    client = _client()
    session_a, _ = _new_game(client, seed=1, starting_bankroll=300, max_rolls=100)
    session_b, _ = _new_game(client, seed=2, starting_bankroll=300, max_rolls=100)

    totals_a = [
        client.post(f"/api/game/{session_a}/roll").json()["view"]["last_roll"]["total"]
        for _ in range(20)
    ]
    totals_b = [
        client.post(f"/api/game/{session_b}/roll").json()["view"]["last_roll"]["total"]
        for _ in range(20)
    ]
    assert totals_a != totals_b


def test_illegal_but_wellformed_bet_is_200_with_ok_false() -> None:
    """take on the come-out is refused by the controller, not by HTTP."""
    client = _client()
    session_id, _ = _new_game(client, seed=1)
    resp = client.post(
        f"/api/game/{session_id}/bet",
        json={"kind": "take", "number": 4, "amount": 10},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["ok"] is False
    # The refusal must explain WHY (odds need an established point), not just fail.
    assert "point" in data["message"].lower() or "odds" in data["message"].lower()


def test_illegal_free_text_bet_is_200_with_ok_false() -> None:
    client = _client()
    session_id, _ = _new_game(client, seed=1)
    resp = client.post(f"/api/game/{session_id}/bet", json={"text": "take 4:10"})
    assert resp.status_code == 200
    data = resp.json()
    assert data["ok"] is False
    assert "point" in data["message"].lower() or "odds" in data["message"].lower()


def test_empty_bet_body_is_422() -> None:
    """Neither structured amount nor text -> client error, not a placed bet."""
    client = _client()
    session_id, _ = _new_game(client, seed=1)
    resp = client.post(f"/api/game/{session_id}/bet", json={})
    assert resp.status_code == 422
    assert resp.json()["detail"]


def test_unknown_session_get_is_404() -> None:
    client = _client()
    resp = client.get("/api/game/does-not-exist")
    assert resp.status_code == 404


def test_unknown_session_bet_is_404() -> None:
    client = _client()
    resp = client.post(
        "/api/game/does-not-exist/bet",
        json={"kind": "pass", "amount": 10},
    )
    assert resp.status_code == 404


def test_unknown_session_roll_is_404() -> None:
    client = _client()
    resp = client.post("/api/game/does-not-exist/roll")
    assert resp.status_code == 404


def test_sessions_are_isolated() -> None:
    client = _client()
    session_a, _ = _new_game(client, seed=1)
    session_b, _ = _new_game(client, seed=1)

    client.post(f"/api/game/{session_a}/bet", json={"kind": "pass", "amount": 10})

    view_a = client.get(f"/api/game/{session_a}").json()
    view_b = client.get(f"/api/game/{session_b}").json()
    assert len(view_a["active_bets"]) == 1
    assert view_b["active_bets"] == []


def test_game_over_reason_surfaced_and_further_actions_refused() -> None:
    """max_rolls=1 terminates after one roll; a later roll/bet is refused."""
    client = _client()
    session_id, _ = _new_game(client, seed=1, starting_bankroll=300, max_rolls=1)

    first = client.post(f"/api/game/{session_id}/roll").json()
    assert first["view"]["game_over"] is True
    assert first["view"]["game_over_reason"] == "max rolls reached"

    # A subsequent roll is refused (ok=false), still HTTP 200.
    again = client.post(f"/api/game/{session_id}/roll")
    assert again.status_code == 200
    assert again.json()["ok"] is False

    # A subsequent bet is refused too.
    bet = client.post(f"/api/game/{session_id}/bet", json={"kind": "pass", "amount": 10})
    assert bet.status_code == 200
    assert bet.json()["ok"] is False


def test_game_over_via_loss_limit() -> None:
    """A loss_limit at/above starting bankroll busts on the first roll."""
    client = _client()
    session_id, _ = _new_game(
        client,
        seed=1,
        starting_bankroll=300,
        max_rolls=100,
        loss_limit=300,
    )
    resp = client.post(f"/api/game/{session_id}/roll").json()
    assert resp["view"]["game_over"] is True
    assert resp["view"]["game_over_reason"] == "bust"


def test_win_goal_defaults_and_custom() -> None:
    """win_goal defaults to None (no goal) and can be set explicitly."""
    client = _client()
    # Custom win goal just below start: any first roll that doesn't lose triggers goal.
    session_id, _ = _new_game(
        client,
        seed=1,
        starting_bankroll=300,
        max_rolls=100,
        win_goal=1,
    )
    resp = client.post(f"/api/game/{session_id}/roll").json()
    assert resp["view"]["game_over"] is True
    assert resp["view"]["game_over_reason"] == "goal reached"
