"""Tests for the random and deterministic dice sources."""

import pytest

from craps_engine.dice import Dice, DiceRoll, RandomDice, ScriptedDice


def test_diceroll_total_and_serialize() -> None:
    r = DiceRoll(3, 4)
    assert r.total == 7
    assert r.to_dict() == {"die1": 3, "die2": 4, "total": 7}


def test_diceroll_rejects_out_of_range() -> None:
    with pytest.raises(ValueError, match="7"):
        DiceRoll(7, 1)
    with pytest.raises(ValueError, match="0"):
        DiceRoll(1, 0)


def test_random_dice_is_seed_reproducible() -> None:
    assert RandomDice(seed=42).roll() == RandomDice(seed=42).roll()
    d = RandomDice(seed=7).roll()
    assert 1 <= d.die1 <= 6
    assert 1 <= d.die2 <= 6


def test_random_dice_sequence_is_reproducible() -> None:
    # Two same-seed instances must produce the identical 10-roll sequence.
    a = RandomDice(seed=1234)
    b = RandomDice(seed=1234)
    assert [a.roll() for _ in range(10)] == [b.roll() for _ in range(10)]


def test_random_dice_dice_are_independent() -> None:
    # Over many rolls, the two dice should not be locked together; a mismatch
    # proves they are independent draws rather than one value duplicated.
    d = RandomDice(seed=99)
    assert any(roll.die1 != roll.die2 for roll in (d.roll() for _ in range(20)))


def test_scripted_dice_feeds_exact_rolls() -> None:
    d = ScriptedDice([(6, 1), (4, 4)])
    assert d.roll().total == 7
    assert d.roll() == DiceRoll(4, 4)


def test_scripted_dice_raises_when_exhausted() -> None:
    with pytest.raises(IndexError, match="exhausted"):
        ScriptedDice([]).roll()


def test_scripted_dice_validates_values_eagerly() -> None:
    # Out-of-range scripted values fail fast at construction, via DiceRoll.
    with pytest.raises(ValueError, match="7"):
        ScriptedDice([(7, 1)])


def test_dice_protocol_runtime_checkable() -> None:
    assert isinstance(RandomDice(), Dice)
    assert isinstance(ScriptedDice([(1, 1)]), Dice)
    assert not isinstance(object(), Dice)
