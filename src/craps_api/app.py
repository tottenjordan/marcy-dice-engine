"""FastAPI app factory wrapping :class:`PlayController` behind a JSON API.

Handlers are deliberately THIN: they resolve a session from the store, translate
the request body into an engine call (via the small pure helpers below), and
return the controller's own ``to_dict()`` payload. All game rules, legality, and
serialization already live in the engine — this layer adds only session
management and request/response plumbing.

Endpoints (all under ``/api``):

- ``POST /api/game`` — create a game; returns ``{session_id, view}`` (HTTP 201).
- ``GET  /api/game/{session_id}`` — the current ``GameView`` (404 if unknown).
- ``POST /api/game/{session_id}/bet`` — place a structured or free-text bet;
  returns ``PlaceOutcome`` (200 even for a legal-but-refused bet; 404 unknown id;
  422 if the body has neither structured amount nor text).
- ``POST /api/game/{session_id}/roll`` — roll once; returns ``RollOutcome``.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, TypedDict

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

from craps_api.session_store import SessionNotFoundError, SessionStore
from craps_engine.specs import BetSpec

if TYPE_CHECKING:
    from craps_engine.play import (
        GameViewPayload,
        PlaceOutcomePayload,
        PlayController,
        RollOutcomePayload,
    )


class NewGamePayload(TypedDict):
    """Serialized shape of ``POST /api/game``'s response: ``{session_id, view}``."""

    session_id: str
    view: GameViewPayload


# The engine's ``to_dict()`` payloads (and :class:`NewGamePayload`) are plain
# ``typing.TypedDict``s, which give ``ty`` precise, accurate handler return types.
# ``from __future__ import annotations`` keeps every annotation a string, so these
# imports stay under TYPE_CHECKING and are never evaluated at runtime. Pydantic on
# Python < 3.12 also refuses ``typing.TypedDict`` for schema generation, so every
# route returning one carries ``response_model=None`` to skip Pydantic's response
# validation while STILL returning the exact serialized payload. Once the floor is
# Python 3.12 the flag can be dropped and OpenAPI schemas come for free.

# Default game knobs when the client omits them.
_DEFAULT_STARTING_BANKROLL = 300
_DEFAULT_MAX_ROLLS = 100


class NewGameRequest(BaseModel):
    """JSON body for ``POST /api/game`` — every field has a sensible default."""

    seed: int | None = None
    starting_bankroll: int = _DEFAULT_STARTING_BANKROLL
    max_rolls: int = _DEFAULT_MAX_ROLLS
    win_goal: int | None = None
    loss_limit: int = 0


class BetRequest(BaseModel):
    """JSON body for placing a bet: EITHER structured fields OR free ``text``.

    All fields are optional at the schema level so we can return a precise 422
    (rather than a generic Pydantic error) when the body carries neither a
    structured ``amount`` nor ``text``.
    """

    kind: str | None = None
    number: int | None = None
    amount: int | None = None
    text: str | None = None


def _controller_or_404(store: SessionStore, session_id: str) -> PlayController:
    """Look up a controller, mapping a store miss to an HTTP 404."""
    try:
        return store.get(session_id)
    except SessionNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


def _place(controller: PlayController, body: BetRequest) -> PlaceOutcomePayload:
    """Route a bet body to the controller: free text, else structured spec.

    ``text`` takes precedence (it flows through ``place_bet_text``, which also
    catches grammar errors). Otherwise a structured ``amount`` builds a
    :class:`BetSpec` for ``place_bet``. A body with neither is a client error
    (422) — an empty bet has no meaning.
    """
    if body.text is not None:
        return controller.place_bet_text(body.text).to_dict()
    if body.amount is not None and body.kind is not None:
        spec = BetSpec(kind=body.kind, amount=body.amount, number=body.number)
        return controller.place_bet(spec).to_dict()
    raise HTTPException(
        status_code=422,
        detail="bet body must supply either {kind, amount[, number]} or {text}",
    )


def create_app() -> FastAPI:
    """Build the FastAPI app with its own in-memory :class:`SessionStore`.

    The store is attached to ``app.state`` so it is discoverable/testable and so
    each ``create_app()`` call yields a fully isolated set of games.
    """
    app = FastAPI(title="Craps Play API")
    store = SessionStore()
    app.state.store = store

    @app.post("/api/game", status_code=201, response_model=None)
    def new_game(body: NewGameRequest) -> NewGamePayload:
        """Create a game and return ``{session_id, view}`` (come-out snapshot)."""
        session_id, controller = store.create(
            starting_bankroll=body.starting_bankroll,
            max_rolls=body.max_rolls,
            win_goal=body.win_goal,
            loss_limit=body.loss_limit,
            seed=body.seed,
        )
        return {"session_id": session_id, "view": controller.snapshot().to_dict()}

    @app.get("/api/game/{session_id}", response_model=None)
    def get_game(session_id: str) -> GameViewPayload:
        """Return the current :class:`GameView` for a session (404 if unknown)."""
        return _controller_or_404(store, session_id).snapshot().to_dict()

    @app.post("/api/game/{session_id}/bet", response_model=None)
    def place_bet(session_id: str, body: BetRequest) -> PlaceOutcomePayload:
        """Place one bet; a legal-but-refused bet still returns 200 with ``ok=false``."""
        controller = _controller_or_404(store, session_id)
        return _place(controller, body)

    @app.post("/api/game/{session_id}/roll", response_model=None)
    def roll(session_id: str) -> RollOutcomePayload:
        """Roll once and return the :class:`RollOutcome` (404 if unknown id)."""
        return _controller_or_404(store, session_id).roll().to_dict()

    return app
