"""Tests for the single-session runner: :class:`Table` and ``run_session``.

These exercise the deterministic roll-ordering contract end to end with
:class:`~craps_engine.dice.ScriptedDice`, the net-worth ``delta`` accounting, the
bust-before-goal termination precedence, the peak/trough trajectory (which
INCLUDES the starting bankroll), the post-roll-only ``history``, and the
serialization round-trip. A tiny in-file probe strategy stands in for the
concrete strategies that arrive in a later task.
"""

from __future__ import annotations

from fractions import Fraction

from craps_engine.bets.base import Resolution, ResolutionStatus
from craps_engine.bets.line import PassLine
from craps_engine.dice import DiceRoll, ScriptedDice
from craps_engine.session import (
    SessionConfig,
    SessionResult,
    SettleResult,
    Strategy,
    Table,
    run_session,
)
from craps_engine.state import GameState, Phase, PhaseTransition


class _PassLineProbe:
    """A minimal idempotent strategy: a single Pass Line on every come-out.

    Adds one ``PassLine("pass", unit)`` whenever the table is on the come-out
    and no live bet already carries that id, so re-invoking it across rolls never
    stacks duplicate wagers.
    """

    def __init__(self, unit: int) -> None:
        self.unit = unit

    def place_bets(self, table: Table) -> None:
        if table.state.phase is Phase.COME_OUT and not any(
            b.id == "pass" for b in table.active_bets()
        ):
            table.add_bet(PassLine("pass", Fraction(self.unit)))


class _RidingBet(PassLine):
    """A bet that always reports NO_ACTION, so it survives every roll.

    Used to prove :meth:`Table.settle` prunes resolved bets while keeping
    unresolved survivors on the table.
    """

    def resolve(self, roll: DiceRoll, state: GameState) -> Resolution:
        del roll, state
        return Resolution(
            bet_id=self.id,
            status=ResolutionStatus.NO_ACTION,
            delta=Fraction(0),
            note="riding",
        )


class TestTable:
    """The mutable :class:`Table` holding live session state."""

    def test_defaults_a_fresh_game_state(self) -> None:
        """When no state is passed, the table starts on a fresh come-out."""
        table = Table(Fraction(100))
        assert isinstance(table.state, GameState)
        assert table.state.phase is Phase.COME_OUT
        assert table.bankroll == Fraction(100)

    def test_accepts_an_explicit_state(self) -> None:
        """A caller-supplied GameState is used as-is."""
        state = GameState()
        table = Table(Fraction(50), state)
        assert table.state is state

    def test_add_and_active_bets(self) -> None:
        """Added bets show up in active_bets."""
        table = Table(Fraction(100))
        bet = PassLine("pass", 10)
        table.add_bet(bet)
        assert table.active_bets() == [bet]

    def test_active_bets_returns_a_copy(self) -> None:
        """Mutating the returned list does NOT change the table's bets."""
        table = Table(Fraction(100))
        table.add_bet(PassLine("pass", 10))
        snapshot = table.active_bets()
        snapshot.clear()
        assert len(table.active_bets()) == 1


class TestTableSettle:
    """The extracted per-roll settlement method :meth:`Table.settle`."""

    def _point_four_table(self, bankroll: int) -> Table:
        """A table already on point 4 (the phase machine advanced past come-out)."""
        state = GameState()
        state.apply(4)  # establish point 4
        assert state.phase is Phase.POINT
        assert state.point == 4
        return Table(Fraction(bankroll), state)

    def test_returns_settle_result_pairing_bets_and_transition(self) -> None:
        """settle returns a SettleResult pairing each live bet with a Resolution
        and the PhaseTransition from applying the rolled total."""
        table = self._point_four_table(300)
        bet = PassLine("pass", Fraction(10))
        table.add_bet(bet)

        result = table.settle(DiceRoll(3, 4))  # seven-out on point 4

        assert isinstance(result, SettleResult)
        assert len(result.settled) == 1
        settled_bet, resolution = result.settled[0]
        assert settled_bet is bet
        assert isinstance(resolution, Resolution)
        assert isinstance(result.transition, PhaseTransition)
        assert result.transition.seven_out is True

    def test_mutates_bankroll_by_sum_of_deltas(self) -> None:
        """settle adds each resolution.delta to bankroll: a PassLine on point 4
        that sees a 7 loses its stake, dropping bankroll by exactly the stake."""
        table = self._point_four_table(300)
        table.add_bet(PassLine("pass", Fraction(10)))

        table.settle(DiceRoll(3, 4))  # seven-out -> LOSE -10

        assert table.bankroll == Fraction(290)

    def test_resolves_before_applying_phase(self) -> None:
        """A PassLine riding point 4 when a 7 lands must resolve as a LOSE
        (seven-out), proving resolution happens BEFORE the phase is applied."""
        table = self._point_four_table(300)
        table.add_bet(PassLine("pass", Fraction(10)))

        result = table.settle(DiceRoll(3, 4))

        _, resolution = result.settled[0]
        assert resolution.status is ResolutionStatus.LOSE
        # The phase machine was applied only AFTER resolution: it is now reset.
        assert table.state.phase is Phase.COME_OUT
        assert table.state.point is None

    def test_prunes_non_survivors_and_keeps_survivors(self) -> None:
        """After a resolving roll a one-and-done bet is pruned from active_bets
        while an unresolved (NO_ACTION) survivor remains.

        A ``PassLine`` on point 4 loses (and comes down) on the 7; a
        ``_RidingBet`` that always reports NO_ACTION stays working.
        """
        table = self._point_four_table(300)
        table.add_bet(PassLine("done", Fraction(10)))  # LOSEs on the 7 -> pruned
        table.add_bet(_RidingBet("rider", Fraction(10)))  # always NO_ACTION

        table.settle(DiceRoll(3, 4))  # seven-out

        ids = [b.id for b in table.active_bets()]
        assert ids == ["rider"]


class TestRunSessionOutcomes:
    """End-to-end resolution and accounting via scripted dice."""

    def test_come_out_seven_win(self) -> None:
        """Come-out 7: Pass wins even money, +10 on a 300 start."""
        dice = ScriptedDice([(3, 4)])
        config = SessionConfig(starting_bankroll=Fraction(300), max_rolls=1)
        result = run_session(dice, _PassLineProbe(10), config)
        assert result.ending_bankroll == Fraction(310)
        assert result.rolls == 1
        assert result.busted is False
        assert result.hit_goal is False

    def test_point_then_seven_out(self) -> None:
        """Establish point 4, then seven-out: Pass loses, -10 on a 300 start."""
        dice = ScriptedDice([(2, 2), (3, 4)])
        config = SessionConfig(starting_bankroll=Fraction(300), max_rolls=2)
        result = run_session(dice, _PassLineProbe(10), config)
        assert result.ending_bankroll == Fraction(290)
        assert result.rolls == 2

    def test_history_records_each_post_roll_bankroll(self) -> None:
        """History has one entry per executed roll: 300 (no action), then 290."""
        dice = ScriptedDice([(2, 2), (3, 4)])
        config = SessionConfig(starting_bankroll=Fraction(300), max_rolls=2)
        result = run_session(dice, _PassLineProbe(10), config)
        assert result.history == [Fraction(300), Fraction(290)]
        assert len(result.history) == result.rolls


class TestTermination:
    """Bust / goal termination, including the bust-first precedence."""

    def test_bust_stops_early(self) -> None:
        """A bankroll falling to the loss_limit busts and halts the loop."""
        dice = ScriptedDice([(2, 2), (3, 4)])
        config = SessionConfig(
            starting_bankroll=Fraction(10),
            max_rolls=99,
            loss_limit=Fraction(0),
        )
        result = run_session(dice, _PassLineProbe(10), config)
        assert result.busted is True
        assert result.hit_goal is False
        assert result.rolls == 2
        assert result.ending_bankroll == Fraction(0)

    def test_win_goal_stops_early(self) -> None:
        """Reaching the win_goal sets hit_goal and stops after the winning roll."""
        dice = ScriptedDice([(3, 4), (3, 4)])
        config = SessionConfig(
            starting_bankroll=Fraction(300),
            max_rolls=99,
            win_goal=Fraction(305),
        )
        result = run_session(dice, _PassLineProbe(10), config)
        assert result.hit_goal is True
        assert result.busted is False
        assert result.rolls == 1
        assert result.ending_bankroll == Fraction(310)

    def test_max_rolls_caps_the_loop(self) -> None:
        """With no bust/goal, the loop runs exactly max_rolls times."""
        dice = ScriptedDice([(3, 4), (3, 4), (3, 4)])
        config = SessionConfig(starting_bankroll=Fraction(300), max_rolls=3)
        result = run_session(dice, _PassLineProbe(10), config)
        assert result.rolls == 3
        assert result.ending_bankroll == Fraction(330)


class TestPeakTrough:
    """Peak/trough span the trajectory INCLUDING the starting bankroll."""

    def test_peak_and_trough_include_start(self) -> None:
        """Win then lose: peak is the high (310), trough is the start (300)."""
        # Roll 1: come-out 7 -> +10 (310). Roll 2: come-out craps 3 -> -10 (300).
        dice = ScriptedDice([(3, 4), (1, 2)])
        config = SessionConfig(starting_bankroll=Fraction(300), max_rolls=2)
        result = run_session(dice, _PassLineProbe(10), config)
        assert result.peak == Fraction(310)
        # Trough never dips below the 300 start in this run.
        assert result.trough == Fraction(300)
        assert result.peak >= config.starting_bankroll
        assert result.trough <= result.peak

    def test_trough_can_be_the_start_when_only_winning(self) -> None:
        """A purely winning run has its trough pinned at the starting bankroll."""
        dice = ScriptedDice([(3, 4)])
        config = SessionConfig(starting_bankroll=Fraction(300), max_rolls=1)
        result = run_session(dice, _PassLineProbe(10), config)
        assert result.trough == Fraction(300)
        assert result.peak == Fraction(310)


class TestSerialization:
    """SessionResult.to_dict round-trips Fractions and the history list."""

    def test_to_dict_shape(self) -> None:
        """Fractions serialize as money payloads; ints/bools pass through."""
        dice = ScriptedDice([(3, 4)])
        config = SessionConfig(starting_bankroll=Fraction(300), max_rolls=1)
        result = run_session(dice, _PassLineProbe(10), config)
        payload = result.to_dict()
        assert payload["ending_bankroll"]["exact"] == "310/1"
        assert payload["peak"]["exact"] == "310/1"
        assert payload["trough"]["exact"] == "300/1"
        assert payload["rolls"] == 1
        assert payload["busted"] is False
        assert payload["hit_goal"] is False
        assert isinstance(payload["history"], list)
        assert payload["history"][0]["exact"] == "310/1"


class TestStrategyProtocol:
    """The Strategy protocol is runtime-checkable."""

    def test_probe_satisfies_protocol(self) -> None:
        """A duck-typed probe is recognized as a Strategy via isinstance."""
        assert isinstance(_PassLineProbe(10), Strategy)


def test_session_result_is_a_dataclass_instance() -> None:
    """run_session returns a SessionResult."""
    dice = ScriptedDice([(3, 4)])
    config = SessionConfig(starting_bankroll=Fraction(300), max_rolls=1)
    assert isinstance(run_session(dice, _PassLineProbe(10), config), SessionResult)
