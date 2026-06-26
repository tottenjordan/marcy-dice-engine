"""Tests for the concrete starter strategies in :mod:`craps_engine.strategy`.

Each strategy must satisfy the structural :class:`~craps_engine.session.Strategy`
Protocol AND honor the idempotency contract: ``place_bets`` is called before every
roll, so re-invoking it must never stack a second wager with an id that is already
live. The tests drive a real :class:`~craps_engine.session.Table`, push it onto a
point via ``table.state.apply(...)`` directly, and assert the exact bets placed
(types, ids, amounts, bound numbers) -- including the showcase reproduction for
:class:`DontPassPlaceStrategy`.
"""

from __future__ import annotations

from fractions import Fraction

from craps_engine.bets.line import DontPass, PassLine
from craps_engine.bets.odds import TakeOdds
from craps_engine.bets.place import PlaceBet
from craps_engine.session import Strategy, Table
from craps_engine.strategy import (
    DontPassPlaceStrategy,
    PassLineOddsStrategy,
    PassLineStrategy,
)


def _bet_by_id(table: Table, bet_id: str) -> object | None:
    """Return the single live bet carrying ``bet_id``, or ``None`` if absent."""
    for bet in table.active_bets():
        if bet.id == bet_id:
            return bet
    return None


class TestProtocolConformance:
    """All three starters conform to the runtime-checkable Strategy Protocol."""

    def test_all_starters_are_strategies(self) -> None:
        """Each concrete starter is recognized by ``isinstance(s, Strategy)``."""
        assert isinstance(PassLineStrategy(), Strategy)
        assert isinstance(PassLineOddsStrategy(), Strategy)
        assert isinstance(DontPassPlaceStrategy(), Strategy)


class TestPassLineStrategy:
    """The flat Pass Line starter."""

    def test_adds_one_pass_line_on_come_out(self) -> None:
        """On a fresh come-out it adds exactly one PassLine id ``pass``."""
        table = Table(Fraction(100))
        PassLineStrategy(Fraction(10)).place_bets(table)
        bets = table.active_bets()
        assert len(bets) == 1
        pass_bet = bets[0]
        assert isinstance(pass_bet, PassLine)
        assert pass_bet.id == "pass"
        assert pass_bet.amount == Fraction(10)

    def test_default_unit_is_ten(self) -> None:
        """The unit defaults to 10 and normalizes to a Fraction."""
        table = Table(Fraction(100))
        PassLineStrategy().place_bets(table)
        pass_bet = _bet_by_id(table, "pass")
        assert isinstance(pass_bet, PassLine)
        assert pass_bet.amount == Fraction(10)

    def test_idempotent_second_call_adds_nothing(self) -> None:
        """A second come-out call does not stack a duplicate pass bet."""
        table = Table(Fraction(100))
        strategy = PassLineStrategy(Fraction(10))
        strategy.place_bets(table)
        strategy.place_bets(table)
        assert len(table.active_bets()) == 1

    def test_does_nothing_on_point_with_no_pass(self) -> None:
        """On the POINT phase it only acts on come-out, so it adds nothing."""
        table = Table(Fraction(100))
        table.state.apply(4)
        PassLineStrategy(Fraction(10)).place_bets(table)
        assert table.active_bets() == []


class TestPassLineOddsStrategy:
    """The Pass Line starter that backs a set point with free odds."""

    def test_come_out_adds_pass_only(self) -> None:
        """On the come-out it adds just the pass bet, no odds yet."""
        table = Table(Fraction(100))
        PassLineOddsStrategy(Fraction(10)).place_bets(table)
        assert _bet_by_id(table, "pass") is not None
        assert _bet_by_id(table, "odds") is None

    def test_backs_point_with_odds(self) -> None:
        """Once a point is set with a pass active, it adds TakeOdds id ``odds``."""
        table = Table(Fraction(100))
        strategy = PassLineOddsStrategy(Fraction(10))
        strategy.place_bets(table)
        table.state.apply(4)
        strategy.place_bets(table)
        odds = _bet_by_id(table, "odds")
        assert isinstance(odds, TakeOdds)
        assert odds.number == 4
        assert odds.amount == Fraction(10)

    def test_idempotent_does_not_restack_odds(self) -> None:
        """A second POINT call does not stack a duplicate odds bet."""
        table = Table(Fraction(100))
        strategy = PassLineOddsStrategy(Fraction(10))
        strategy.place_bets(table)
        table.state.apply(4)
        strategy.place_bets(table)
        strategy.place_bets(table)
        odds_bets = [b for b in table.active_bets() if b.id == "odds"]
        assert len(odds_bets) == 1

    def test_no_odds_when_no_pass_active(self) -> None:
        """With a point set but no pass bet, no odds are added."""
        table = Table(Fraction(100))
        table.state.apply(4)
        PassLineOddsStrategy(Fraction(10)).place_bets(table)
        assert _bet_by_id(table, "odds") is None


class TestDontPassPlaceStrategy:
    """The hedged Don't-Pass + Place 6/8 showcase reproduction."""

    def test_come_out_adds_dont_pass(self) -> None:
        """On the come-out it adds DontPass id ``dp`` at the line unit."""
        table = Table(Fraction(100))
        DontPassPlaceStrategy().place_bets(table)
        dp = _bet_by_id(table, "dp")
        assert isinstance(dp, DontPass)
        assert dp.amount == Fraction(10)

    def test_point_adds_place_six_and_eight(self) -> None:
        """Once on a point it adds working Place 6 and Place 8 at the place unit."""
        table = Table(Fraction(100))
        strategy = DontPassPlaceStrategy()
        strategy.place_bets(table)
        table.state.apply(4)
        strategy.place_bets(table)
        p6 = _bet_by_id(table, "p6")
        p8 = _bet_by_id(table, "p8")
        assert isinstance(p6, PlaceBet)
        assert isinstance(p8, PlaceBet)
        assert p6.number == 6
        assert p8.number == 8
        assert p6.amount == Fraction(6)
        assert p8.amount == Fraction(6)
        assert p6.working is True
        assert p8.working is True

    def test_reproduces_showcase_portfolio(self) -> None:
        """The end state after a point is set matches the showcase exactly."""
        table = Table(Fraction(100))
        strategy = DontPassPlaceStrategy()
        strategy.place_bets(table)
        table.state.apply(4)
        strategy.place_bets(table)
        by_id = {b.id: b for b in table.active_bets()}
        assert set(by_id) == {"dp", "p6", "p8"}
        assert isinstance(by_id["dp"], DontPass)
        assert isinstance(by_id["p6"], PlaceBet)
        assert isinstance(by_id["p8"], PlaceBet)
        assert by_id["dp"].amount == Fraction(10)
        assert by_id["p6"].amount == Fraction(6)
        assert by_id["p8"].amount == Fraction(6)
        assert by_id["p6"].number == 6
        assert by_id["p8"].number == 8

    def test_idempotent_no_duplicates(self) -> None:
        """Re-invoking on the come-out and the point never stacks duplicates."""
        table = Table(Fraction(100))
        strategy = DontPassPlaceStrategy()
        strategy.place_bets(table)
        strategy.place_bets(table)
        table.state.apply(4)
        strategy.place_bets(table)
        strategy.place_bets(table)
        ids = [b.id for b in table.active_bets()]
        assert sorted(ids) == ["dp", "p6", "p8"]

    def test_custom_units(self) -> None:
        """Constructor units override the showcase defaults."""
        table = Table(Fraction(100))
        strategy = DontPassPlaceStrategy(line_unit=Fraction(20), place_unit=Fraction(12))
        strategy.place_bets(table)
        table.state.apply(4)
        strategy.place_bets(table)
        by_id = {b.id: b for b in table.active_bets()}
        assert by_id["dp"].amount == Fraction(20)
        assert by_id["p6"].amount == Fraction(12)
        assert by_id["p8"].amount == Fraction(12)
