"""In-memory store of live :class:`PlayController` games keyed by session id.

Each browser/API session owns one :class:`~craps_engine.play.PlayController`
(itself owning a table, a seeded dice source, and a config). This store is the
application-layer glue that mints unique ids, builds a controller from the
request's config knobs, and looks controllers back up between HTTP calls.

Scope: SINGLE-INSTANCE, in-memory ONLY. Games live in one process's memory and
are lost on restart; there is no eviction/TTL. A shared/durable store (e.g.
Redis) for multi-instance deployments is explicit backlog, not implemented here.
This module is stdlib-only apart from referencing engine types.
"""

from __future__ import annotations

import uuid
from fractions import Fraction
from typing import TYPE_CHECKING

from craps_engine.dice import RandomDice
from craps_engine.play import PlayController
from craps_engine.session import SessionConfig

if TYPE_CHECKING:
    from craps_engine.dice import Dice


class SessionNotFoundError(KeyError):
    """Raised when a session id is not present in the store.

    A distinct type so the app layer can map exactly this miss to an HTTP 404
    without swallowing unrelated ``KeyError``s.
    """


class SessionStore:
    """A ``dict[str, PlayController]`` of live games keyed by a generated id.

    Not thread-safe by design: single-instance, in-memory only (see the module
    docstring). Ids are :func:`uuid.uuid4` hexes so they are unique without a
    guessable/sequential scheme.
    """

    def __init__(self) -> None:
        """Start with no live games."""
        self._games: dict[str, PlayController] = {}

    def create(
        self,
        *,
        starting_bankroll: int,
        max_rolls: int,
        win_goal: int | None = None,
        loss_limit: int = 0,
        seed: int | None = None,
    ) -> tuple[str, PlayController]:
        """Build and store a new game, returning ``(session_id, controller)``.

        Whole-dollar int knobs are converted to exact :class:`~fractions.Fraction`
        money for the engine. ``seed`` seeds a :class:`RandomDice` (``None`` =
        nondeterministic). A fresh :func:`uuid.uuid4` hex is the session id.
        """
        config = SessionConfig(
            starting_bankroll=Fraction(starting_bankroll),
            max_rolls=max_rolls,
            win_goal=None if win_goal is None else Fraction(win_goal),
            loss_limit=Fraction(loss_limit),
        )
        dice: Dice = RandomDice(seed)
        controller = PlayController(dice, config)
        session_id = uuid.uuid4().hex
        self._games[session_id] = controller
        return session_id, controller

    def get(self, session_id: str) -> PlayController:
        """Return the controller for ``session_id`` or raise :class:`SessionNotFoundError`."""
        try:
            return self._games[session_id]
        except KeyError:
            msg = f"no game for session id {session_id!r}"
            raise SessionNotFoundError(msg) from None
