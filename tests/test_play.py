"""Tests for the pure interactive play controller (:mod:`craps_engine.play`).

These exercise the single ``place_bet`` funnel (buttons and free text share it),
monotonic bet ids, scripted win/lose trajectories, the bust/goal game-over
gates, odds legality, seed reproducibility, and the serialized :class:`GameView`
shape. :class:`~craps_engine.dice.ScriptedDice` supplies deterministic rolls;
the ``serialize_fraction`` money-payload shape is asserted against the
``exact``/``float``/``display`` keys.
"""

from __future__ import annotations

from fractions import Fraction

from craps_engine.dice import RandomDice, ScriptedDice
from craps_engine.play import GameView, PlaceOutcome, PlayController, RollOutcome
from craps_engine.session import SessionConfig
from craps_engine.specs import BetSpec
from craps_engine.state import Phase


def _config(**kwargs: object) -> SessionConfig:
    """A default 300-bankroll, 99-roll config with optional overrides."""
    base: dict[str, object] = {
        "starting_bankroll": Fraction(300),
        "max_rolls": 99,
    }
    base.update(kwargs)
    return SessionConfig(**base)  # type: ignore[arg-type]


# --- the single place-bet funnel -------------------------------------------


def test_button_spec_funnel_equals_free_text_funnel() -> None:
    """A BetSpec placed directly matches the same bet placed via free text."""
    a = PlayController(ScriptedDice([]), _config())
    a.place_bet(BetSpec("pass", 10))

    b = PlayController(ScriptedDice([]), _config())
    b.place_bet_text("pass:10")

    bets_a = [(b.id[:-1], b.amount, type(b)) for b in a.snapshot().active_bets]
    bets_b = [(b.id[:-1], b.amount, type(b)) for b in b.snapshot().active_bets]
    assert bets_a == bets_b


def test_place_bet_ok_message_and_view() -> None:
    """A legal placement returns ok=True and a fresh snapshot with the bet."""
    ctrl = PlayController(ScriptedDice([]), _config())
    outcome = ctrl.place_bet(BetSpec("pass", 10))
    assert isinstance(outcome, PlaceOutcome)
    assert outcome.ok is True
    assert len(outcome.view.active_bets) == 1


def test_place_bet_text_parse_error_is_rejected_not_raised() -> None:
    """Malformed free text is rejected (ok=False), never raised."""
    ctrl = PlayController(ScriptedDice([]), _config())
    outcome = ctrl.place_bet_text("garbage")
    assert outcome.ok is False
    assert "parse" in outcome.message


# --- unique, monotonic bet ids ---------------------------------------------


def test_unique_ids_across_placements_and_rolls() -> None:
    """The bet counter is monotonic: every placement gets a distinct id."""
    ctrl = PlayController(ScriptedDice([(1, 2), (1, 2)]), _config())
    ctrl.place_bet(BetSpec("pass", 10))
    ctrl.roll()
    ctrl.place_bet(BetSpec("pass", 10))
    ctrl.place_bet(BetSpec("dontpass", 10))
    ids = [b.id for b in ctrl.snapshot().active_bets]
    assert len(ids) == len(set(ids))


# --- scripted outcomes ------------------------------------------------------


def test_come_out_seven_pass_wins() -> None:
    """Come-out 7 with pass:10 down: Pass WINS, bankroll +10."""
    ctrl = PlayController(ScriptedDice([(3, 4)]), _config())
    ctrl.place_bet_text("pass:10")
    outcome = ctrl.roll()
    assert isinstance(outcome, RollOutcome)
    assert outcome.ok is True
    assert outcome.view.bankroll == Fraction(310)
    assert outcome.view.running_net == Fraction(10)


def test_point_then_seven_out_pass_loses() -> None:
    """Establish point 4, then seven-out: Pass loses, bankroll -10 net."""
    ctrl = PlayController(ScriptedDice([(2, 2), (3, 4)]), _config())
    ctrl.place_bet_text("pass:10")
    ctrl.roll()  # (2,2) -> point 4 established, no action
    assert ctrl.snapshot().phase == Phase.POINT.value
    assert ctrl.snapshot().point == 4
    ctrl.roll()  # (3,4) -> seven-out
    view = ctrl.snapshot()
    assert view.bankroll == Fraction(290)
    assert view.running_net == Fraction(-10)


# --- game-over gates --------------------------------------------------------


def test_bust_game_over_blocks_further_play() -> None:
    """Reaching the loss_limit ends the game; roll/place then reject."""
    ctrl = PlayController(
        ScriptedDice([(2, 2), (3, 4)]),
        _config(starting_bankroll=Fraction(10), loss_limit=Fraction(0)),
    )
    ctrl.place_bet_text("pass:10")
    ctrl.roll()  # point 4
    over = ctrl.roll()  # seven-out -> bankroll 0 -> bust
    assert over.view.game_over is True
    assert over.view.game_over_reason == "bust"

    assert ctrl.roll().ok is False
    assert ctrl.place_bet(BetSpec("pass", 10)).ok is False


def test_goal_game_over_blocks_further_play() -> None:
    """Reaching win_goal ends the game as a winner; roll/place then reject."""
    ctrl = PlayController(
        ScriptedDice([(3, 4)]),
        _config(win_goal=Fraction(305)),
    )
    ctrl.place_bet_text("pass:10")
    over = ctrl.roll()  # +10 -> 310 >= 305
    assert over.view.game_over is True
    assert over.view.game_over_reason == "goal reached"

    assert ctrl.roll().ok is False
    assert ctrl.place_bet_text("pass:10").ok is False


def test_max_rolls_game_over() -> None:
    """Hitting max_rolls ends the game with the max-rolls reason."""
    ctrl = PlayController(ScriptedDice([(1, 2)]), _config(max_rolls=1))
    ctrl.roll()
    view = ctrl.snapshot()
    assert view.game_over is True
    assert view.game_over_reason == "max rolls reached"
    assert view.rolls_used == 1
    assert view.rolls_left == 0


# --- odds legality ----------------------------------------------------------


def test_take_odds_off_point_rejected() -> None:
    """On the come-out, take odds are illegal (no established point)."""
    ctrl = PlayController(ScriptedDice([]), _config())
    outcome = ctrl.place_bet(BetSpec("take", 10, number=4))
    assert outcome.ok is False
    assert "point" in outcome.message


def test_take_odds_accepts_current_point_rejects_wrong_one() -> None:
    """After point 4 is set, take 4 is accepted but take 5 (wrong point) is not."""
    ctrl = PlayController(ScriptedDice([(2, 2)]), _config())
    ctrl.place_bet_text("pass:10")
    ctrl.roll()  # establish point 4
    assert ctrl.snapshot().point == 4

    good = ctrl.place_bet(BetSpec("take", 10, number=4))
    assert good.ok is True

    bad = ctrl.place_bet(BetSpec("take", 10, number=5))
    assert bad.ok is False
    assert "current point" in bad.message


def test_odds_available_flag_tracks_phase() -> None:
    """odds_available is True only during the POINT phase."""
    ctrl = PlayController(ScriptedDice([(2, 2)]), _config())
    assert ctrl.snapshot().odds_available is False
    ctrl.place_bet_text("pass:10")
    ctrl.roll()  # point 4
    assert ctrl.snapshot().odds_available is True


# --- seed reproducibility ---------------------------------------------------


def test_seed_reproducibility() -> None:
    """Two controllers seeded the same roll identical trajectories."""
    a = PlayController(RandomDice(1234), _config())
    b = PlayController(RandomDice(1234), _config())
    for _ in range(20):
        a.place_bet_text("pass:5")
        b.place_bet_text("pass:5")
        ra = a.roll()
        rb = b.roll()
        assert ra.view.bankroll == rb.view.bankroll
        assert ra.view.last_roll is not None
        assert rb.view.last_roll is not None
        assert ra.view.last_roll.to_dict() == rb.view.last_roll.to_dict()


# --- GameView serialization -------------------------------------------------


def test_snapshot_before_first_roll_has_no_last_roll() -> None:
    """Before rolling, last_roll is None and last_outcomes is empty."""
    ctrl = PlayController(ScriptedDice([]), _config())
    view = ctrl.snapshot()
    assert view.last_roll is None
    assert view.last_outcomes == []


def test_gameview_to_dict_shape() -> None:
    """to_dict yields the expected keys with money fields serialized."""
    ctrl = PlayController(ScriptedDice([(3, 4)]), _config())
    ctrl.place_bet_text("pass:10")
    view = ctrl.roll().view
    payload = view.to_dict()

    for key in (
        "starting_bankroll",
        "bankroll",
        "running_net",
        "phase",
        "point",
        "active_bets",
        "last_roll",
        "last_outcomes",
        "rolls_used",
        "rolls_left",
        "game_over",
        "game_over_reason",
        "odds_available",
    ):
        assert key in payload

    # Money fields carry the serialize_fraction payload shape.
    for money_key in ("starting_bankroll", "bankroll", "running_net"):
        assert set(payload[money_key]) == {"exact", "float", "display"}
    assert payload["bankroll"]["exact"] == "310/1"

    assert isinstance(payload["active_bets"], list)
    assert isinstance(payload["last_outcomes"], list)
    assert all(isinstance(b, dict) for b in payload["active_bets"])
    assert all(isinstance(o, dict) for o in payload["last_outcomes"])
    assert isinstance(payload["last_roll"], dict)
    assert payload["last_roll"]["total"] == 7


def test_gameview_to_dict_last_roll_none_before_first_roll() -> None:
    """last_roll serializes to None before any roll."""
    ctrl = PlayController(ScriptedDice([]), _config())
    payload = ctrl.snapshot().to_dict()
    assert payload["last_roll"] is None
    assert payload["last_outcomes"] == []


def test_place_and_roll_outcome_to_dict() -> None:
    """PlaceOutcome / RollOutcome serialize to {ok, message, view}."""
    ctrl = PlayController(ScriptedDice([(3, 4)]), _config())
    place = ctrl.place_bet_text("pass:10")
    place_payload = place.to_dict()
    assert set(place_payload) == {"ok", "message", "view"}
    assert place_payload["ok"] is True
    assert isinstance(place_payload["view"], dict)

    roll_payload = ctrl.roll().to_dict()
    assert set(roll_payload) == {"ok", "message", "view"}
    assert roll_payload["ok"] is True


def test_isinstance_gameview() -> None:
    """snapshot returns a GameView instance."""
    ctrl = PlayController(ScriptedDice([]), _config())
    assert isinstance(ctrl.snapshot(), GameView)
