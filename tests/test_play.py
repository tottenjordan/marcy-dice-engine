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
from craps_engine.play import (
    GameView,
    PlaceOutcome,
    PlayController,
    RollOutcome,
    _odds_prompt_applies,
    coaching_hint,
)
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


# --- wallet/cash bankroll view ----------------------------------------------


def test_place_bet_deducts_stake_from_wallet() -> None:
    """Placing a bet lowers the wallet bankroll (and net) by its stake."""
    ctrl = PlayController(ScriptedDice([]), _config())
    ctrl.place_bet(BetSpec("pass", 10))
    view = ctrl.snapshot()
    assert view.bankroll == Fraction(290)
    assert view.running_net == Fraction(-10)


def test_wallet_and_on_table_stakes_sum_to_net_worth() -> None:
    """The wallet identity holds: wallet + Σ stakes == net worth (unchanged by placing)."""
    ctrl = PlayController(ScriptedDice([]), _config())
    ctrl.place_bet(BetSpec("pass", 10))
    ctrl.place_bet(BetSpec("place", 12, number=6))
    view = ctrl.snapshot()
    on_table = sum((b.amount for b in view.active_bets), Fraction(0))
    assert view.bankroll == Fraction(278)
    assert view.bankroll + on_table == Fraction(300)


def test_game_over_judged_on_net_worth_not_wallet() -> None:
    """A wallet dipping below the loss limit does NOT bust while net worth is safe.

    Chips resting on the felt are still yours, so committing most of the bankroll
    to a standing bet must not end the game even though the *wallet* figure drops
    below ``loss_limit``.
    """
    ctrl = PlayController(ScriptedDice([(2, 2)]), _config(loss_limit=Fraction(50)))
    ctrl.place_bet(BetSpec("pass", 260))
    ctrl.roll()  # (2,2) -> point 4; pass bet stays up, net worth still 300
    view = ctrl.snapshot()
    assert view.bankroll == Fraction(40)  # wallet is below the $50 loss limit
    assert view.game_over is False  # but net worth ($300) keeps the game live


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


def test_uncapped_never_ends_by_rolls() -> None:
    """With max_rolls=None (and no reachable bust/goal), the game never ends by rolls.

    Drive 200+ come-out sevens (which just win even money): with no cap the game
    stays live no matter how many rolls elapse. RandomDice is avoided so the
    trajectory is fully deterministic.
    """
    ctrl = PlayController(
        ScriptedDice([(3, 4)] * 250),
        _config(max_rolls=None),
    )
    for _ in range(250):
        ctrl.place_bet_text("pass:10")
        outcome = ctrl.roll()
        assert outcome.ok is True
        assert outcome.view.game_over is False
    view = ctrl.snapshot()
    assert view.game_over is False
    assert view.rolls_used == 250


def test_uncapped_rolls_left_is_none() -> None:
    """When uncapped, rolls_left is None; when capped, it is an int."""
    uncapped = PlayController(ScriptedDice([]), _config(max_rolls=None))
    assert uncapped.snapshot().rolls_left is None

    capped = PlayController(ScriptedDice([]), _config(max_rolls=10))
    assert capped.snapshot().rolls_left == 10


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


# --- recent roll history ----------------------------------------------------


def test_recent_rolls_empty_before_any_roll() -> None:
    """recent_rolls is empty before the first roll."""
    ctrl = PlayController(ScriptedDice([]), _config())
    assert ctrl.snapshot().recent_rolls == []


def test_recent_rolls_fewer_than_ten_newest_first() -> None:
    """After N<10 rolls it holds exactly N entries, newest-first.

    Uses distinguishable rolls (no bets down, so totals never trigger a
    game-over gate) and asserts the first entry is the most recent roll and the
    last entry is the oldest.
    """
    script = [(1, 1), (1, 2), (2, 2), (2, 3)]  # totals 2, 3, 4, 5
    ctrl = PlayController(ScriptedDice(script), _config())
    for _ in script:
        ctrl.roll()

    recent = ctrl.snapshot().recent_rolls
    assert len(recent) == len(script)
    # Newest-first: first entry is the last-rolled (2,3); last is the first (1,1).
    assert (recent[0].die1, recent[0].die2) == (2, 3)
    assert recent[0].total == 5
    assert (recent[-1].die1, recent[-1].die2) == (1, 1)
    assert recent[-1].total == 2
    # Order is exactly the roll sequence reversed.
    assert [(r.die1, r.die2) for r in recent] == list(reversed(script))


def test_recent_rolls_capped_at_ten_newest_first() -> None:
    """After 12 rolls it holds exactly the 10 most recent, newest-first."""
    # 12 distinguishable rolls (totals 2..12, then 2 again) with no bets down.
    script = [
        (1, 1),  # 2
        (1, 2),  # 3
        (1, 3),  # 4
        (1, 4),  # 5
        (1, 5),  # 6
        (1, 6),  # 7
        (2, 6),  # 8
        (3, 6),  # 9
        (4, 6),  # 10
        (5, 6),  # 11
        (6, 6),  # 12
        (1, 1),  # 2 (12th roll, most recent)
    ]
    ctrl = PlayController(ScriptedDice(script), _config())
    for _ in script:
        ctrl.roll()

    recent = ctrl.snapshot().recent_rolls
    assert len(recent) == 10
    # The 10 most recent rolls (script[2:]) reversed = newest-first.
    assert [(r.die1, r.die2) for r in recent] == list(reversed(script[-10:]))
    assert (recent[0].die1, recent[0].die2) == (1, 1)  # newest
    assert (recent[-1].die1, recent[-1].die2) == (1, 3)  # oldest of the kept 10


def test_recent_rolls_serialized_in_to_dict() -> None:
    """to_dict includes recent_rolls as a list of DiceRoll payloads, newest-first."""
    script = [(1, 1), (2, 3)]  # totals 2, 5
    ctrl = PlayController(ScriptedDice(script), _config())
    for _ in script:
        ctrl.roll()

    payload = ctrl.snapshot().to_dict()
    assert "recent_rolls" in payload
    assert isinstance(payload["recent_rolls"], list)
    assert all(isinstance(r, dict) for r in payload["recent_rolls"])
    assert [r["total"] for r in payload["recent_rolls"]] == [5, 2]
    assert payload["recent_rolls"][0] == {"die1": 2, "die2": 3, "total": 5}


# --- remove bet -------------------------------------------------------------


def test_remove_bet_ok_removes_from_view_and_refunds_wallet() -> None:
    """Removing a placed bet succeeds, drops it, and returns its stake to the wallet."""
    ctrl = PlayController(ScriptedDice([]), _config())
    placed = ctrl.place_bet(BetSpec("pass", 10))
    bet = placed.view.active_bets[0]
    bet_id = bet.id
    stake = bet.amount
    before = ctrl.snapshot().bankroll

    outcome = ctrl.remove_bet(bet_id)

    assert isinstance(outcome, PlaceOutcome)
    assert outcome.ok is True
    assert bet_id in outcome.message
    assert outcome.view.active_bets == []
    # Wallet model: taking the bet down returns its stake to the wallet bankroll.
    assert outcome.view.bankroll == before + stake


def test_remove_bet_unknown_id_rejected_no_state_change() -> None:
    """Removing an unknown id is rejected, names the id, and changes nothing."""
    ctrl = PlayController(ScriptedDice([]), _config())
    ctrl.place_bet(BetSpec("pass", 10))
    before = ctrl.snapshot()

    outcome = ctrl.remove_bet("bogus9")

    assert outcome.ok is False
    assert "bogus9" in outcome.message
    assert [b.id for b in outcome.view.active_bets] == [b.id for b in before.active_bets]
    assert outcome.view.bankroll == before.bankroll


def test_remove_bet_refused_when_game_over() -> None:
    """Once the game is over, remove_bet is refused like place_bet."""
    ctrl = PlayController(ScriptedDice([(1, 2)]), _config(max_rolls=1))
    ctrl.place_bet(BetSpec("pass", 10))
    placed_id = ctrl.snapshot().active_bets[0].id
    ctrl.roll()  # max_rolls=1 -> game over
    assert ctrl.snapshot().game_over is True

    outcome = ctrl.remove_bet(placed_id)

    assert outcome.ok is False
    assert "game over" in outcome.message


# --- press bet --------------------------------------------------------------


def test_press_bet_increases_amount_by_win_delta_wallet_drops() -> None:
    """Pressing a just-won Place bet adds its win delta and moves that cash onto the felt."""
    # Place 6 (off on come-out), establish point 4, then roll a 6 -> Place 6 wins.
    ctrl = PlayController(ScriptedDice([(2, 2), (2, 4)]), _config())
    ctrl.place_bet(BetSpec("place", 6, number=6))
    bet_id = ctrl.snapshot().active_bets[0].id
    ctrl.roll()  # (2,2) -> point 4, place 6 no action
    ctrl.roll()  # (2,4) -> total 6, Place 6 WINS

    view = ctrl.snapshot()
    win = next(
        res for res in view.last_outcomes if res.bet_id == bet_id and res.status.value == "win"
    )
    bet = next(b for b in view.active_bets if b.id == bet_id)
    amount_before = bet.amount
    bankroll_before = view.bankroll

    outcome = ctrl.press_bet(bet_id)

    assert outcome.ok is True
    assert bet_id in outcome.message
    pressed = next(b for b in outcome.view.active_bets if b.id == bet_id)
    assert pressed.amount == amount_before + win.delta
    # Wallet model: the pressed winnings move from cash onto the felt, so the
    # wallet bankroll drops by exactly the pressed amount (net worth unchanged).
    assert outcome.view.bankroll == bankroll_before - win.delta


def test_press_bet_no_prior_win_rejected() -> None:
    """A freshly placed bet with no winning roll cannot be pressed."""
    ctrl = PlayController(ScriptedDice([]), _config())
    ctrl.place_bet(BetSpec("place", 6, number=6))
    bet_id = ctrl.snapshot().active_bets[0].id

    outcome = ctrl.press_bet(bet_id)

    assert outcome.ok is False
    assert bet_id in outcome.message


def test_press_bet_unknown_id_rejected() -> None:
    """Pressing an unknown id is rejected and names the id."""
    ctrl = PlayController(ScriptedDice([]), _config())
    ctrl.place_bet(BetSpec("place", 6, number=6))

    outcome = ctrl.press_bet("ghost3")

    assert outcome.ok is False
    assert "ghost3" in outcome.message


def test_press_bet_refused_when_game_over() -> None:
    """Once the game is over, press_bet is refused."""
    ctrl = PlayController(ScriptedDice([(1, 2)]), _config(max_rolls=1))
    ctrl.place_bet(BetSpec("pass", 10))
    placed_id = ctrl.snapshot().active_bets[0].id
    ctrl.roll()  # game over
    assert ctrl.snapshot().game_over is True

    outcome = ctrl.press_bet(placed_id)

    assert outcome.ok is False
    assert "game over" in outcome.message


def test_press_bet_cannot_double_press_same_win_but_next_roll_reenables() -> None:
    """A win presses at most once per roll; a fresh win on a later roll re-enables it."""
    # Point 4 established (2,2); Place 6 wins on (2,4); Place 6 wins AGAIN on (3,3)
    # (a 6 keeps point 4 on, so the bet stays live for a second win).
    ctrl = PlayController(ScriptedDice([(2, 2), (2, 4), (3, 3)]), _config())
    ctrl.place_bet(BetSpec("place", 6, number=6))
    bet_id = ctrl.snapshot().active_bets[0].id
    ctrl.roll()  # (2,2) -> point 4, place 6 no action
    ctrl.roll()  # (2,4) -> total 6, Place 6 WINS

    first_win = next(
        res
        for res in ctrl.snapshot().last_outcomes
        if res.bet_id == bet_id and res.status.value == "win"
    )
    amount_before = next(b for b in ctrl.snapshot().active_bets if b.id == bet_id).amount

    ok = ctrl.press_bet(bet_id)
    assert ok.ok is True
    after_one = next(b for b in ok.view.active_bets if b.id == bet_id).amount
    assert after_one == amount_before + first_win.delta

    # Second press in the SAME roll is refused and does NOT compound the stake.
    again = ctrl.press_bet(bet_id)
    assert again.ok is False
    assert "already pressed this roll" in again.message
    unchanged = next(b for b in again.view.active_bets if b.id == bet_id).amount
    assert unchanged == after_one

    # A new roll into another win for the same bet re-enables pressing.
    ctrl.roll()  # (3,3) -> total 6, Place 6 WINS again
    second_win = next(
        res
        for res in ctrl.snapshot().last_outcomes
        if res.bet_id == bet_id and res.status.value == "win"
    )
    before_second = next(b for b in ctrl.snapshot().active_bets if b.id == bet_id).amount
    ok2 = ctrl.press_bet(bet_id)
    assert ok2.ok is True
    after_second = next(b for b in ok2.view.active_bets if b.id == bet_id).amount
    assert after_second == before_second + second_win.delta


def test_press_bet_non_win_status_with_nonempty_outcomes_rejected() -> None:
    """A bet that resolved NON-WIN on the last roll cannot be pressed.

    On the point-establishing (2,2) roll, ``last_outcomes`` is non-empty (the
    Place 6 resolved NO_ACTION) but carries no WIN for the bet, so the press is
    rejected by the WIN filter rather than by an empty-outcomes path.
    """
    ctrl = PlayController(ScriptedDice([(2, 2)]), _config())
    ctrl.place_bet(BetSpec("place", 6, number=6))
    bet_id = ctrl.snapshot().active_bets[0].id
    ctrl.roll()  # (2,2) -> point 4; Place 6 resolves NO_ACTION, not a WIN

    assert ctrl.snapshot().last_outcomes != []
    outcome = ctrl.press_bet(bet_id)
    assert outcome.ok is False
    assert "did not win on the last roll" in outcome.message


# --- data-driven coaching hints ---------------------------------------------


class TestCoachingHint:
    """First-matching-rule coverage for :func:`coaching_hint`.

    Each test drives a :class:`PlayController` into exactly one rule's state and
    asserts the precise hint string, verifying both the rule table's precedence
    ordering and the ``{point}`` interpolations.
    """

    def test_game_over_bust(self) -> None:
        """A busted game reports the bust game-over message."""
        ctrl = PlayController(
            ScriptedDice([(2, 2), (3, 4)]),
            _config(starting_bankroll=Fraction(10), loss_limit=Fraction(0)),
        )
        ctrl.place_bet_text("pass:10")
        ctrl.roll()  # point 4
        ctrl.roll()  # seven-out -> bust
        view = ctrl.snapshot()
        assert view.game_over_reason == "bust"
        assert coaching_hint(view) == ("Game over — you busted. Start a new game to play again.")

    def test_game_over_goal_reached(self) -> None:
        """Hitting the win goal reports the winner game-over message."""
        ctrl = PlayController(ScriptedDice([(3, 4)]), _config(win_goal=Fraction(305)))
        ctrl.place_bet_text("pass:10")
        ctrl.roll()  # +10 -> goal reached
        view = ctrl.snapshot()
        assert view.game_over_reason == "goal reached"
        assert coaching_hint(view) == "Game over — you hit your win goal!"

    def test_game_over_max_rolls(self) -> None:
        """Exhausting max_rolls reports the out-of-rolls game-over message."""
        ctrl = PlayController(ScriptedDice([(1, 2)]), _config(max_rolls=1))
        ctrl.roll()
        view = ctrl.snapshot()
        assert view.game_over_reason == "max rolls reached"
        assert coaching_hint(view) == ("Game over — out of rolls. Start a new game to play again.")

    def test_come_out_place_bet_off_warning(self) -> None:
        """A non-working PlaceBet on the come-out triggers the place-off warning."""
        ctrl = PlayController(ScriptedDice([]), _config())
        ctrl.place_bet(BetSpec("place", 6, number=6))
        view = ctrl.snapshot()
        assert view.phase == Phase.COME_OUT.value
        assert coaching_hint(view) == (
            "Heads up: place bets are OFF on the come-out roll — they don't win "
            "or lose until a point is set."
        )

    def test_come_out_explainer_default(self) -> None:
        """A plain come-out (no place bet down) gives the Pass line explainer."""
        ctrl = PlayController(ScriptedDice([]), _config())
        ctrl.place_bet_text("pass:10")
        view = ctrl.snapshot()
        assert view.phase == Phase.COME_OUT.value
        assert coaching_hint(view) == (
            "Come-out roll: a Pass line wins on 7 or 11 and loses on 2, 3, or 12."
        )

    def test_point_with_line_no_odds_prompts_odds(self) -> None:
        """On a point with a Pass line and no odds, prompt for free odds."""
        ctrl = PlayController(ScriptedDice([(2, 2)]), _config())
        ctrl.place_bet_text("pass:10")
        ctrl.roll()  # establish point 4
        view = ctrl.snapshot()
        assert view.point == 4
        assert coaching_hint(view) == (
            "Point is 4. You can back your line bet with free odds — the only "
            "zero-house-edge bet in craps."
        )

    def test_point_with_line_and_odds_falls_through_to_generic(self) -> None:
        """A line bet already backed by odds yields the point-generic default."""
        ctrl = PlayController(ScriptedDice([(3, 3)]), _config())
        ctrl.place_bet_text("pass:10")
        ctrl.roll()  # establish point 6
        ctrl.place_bet(BetSpec("take", 10, number=6))
        view = ctrl.snapshot()
        assert view.point == 6
        assert coaching_hint(view) == (
            "Point is 6: roll it again before a 7 to win your Pass line."
        )

    def test_point_with_no_line_bet_falls_through_to_generic(self) -> None:
        """A point with no line bet also yields the point-generic default."""
        ctrl = PlayController(ScriptedDice([(2, 3)]), _config())
        ctrl.place_bet(BetSpec("place", 6, number=5))
        ctrl.roll()  # establish point 5, no line bet present
        view = ctrl.snapshot()
        assert view.point == 5
        assert coaching_hint(view) == (
            "Point is 5: roll it again before a 7 to win your Pass line."
        )

    def test_odds_prompt_guarded_when_odds_unavailable(self) -> None:
        """The odds-prompt predicate is False when odds are not available.

        Guards the ``not odds_available`` branch of the predicate directly: a
        view can carry a line bet while odds are unavailable (e.g. on the
        come-out), and the odds prompt must not fire there.
        """
        ctrl = PlayController(ScriptedDice([]), _config())
        ctrl.place_bet_text("pass:10")  # line bet down, still on the come-out
        view = ctrl.snapshot()
        assert view.odds_available is False
        assert not _odds_prompt_applies(view)
