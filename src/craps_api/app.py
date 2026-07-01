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

On TOP of the JSON API this module also serves a server-rendered, HTMX-driven
browser frontend (see the ``HTML routes`` below). Those routes reuse the SAME
store and controller funnel; they differ only in returning HTML fragments (built
by the pure :func:`craps_api.board.build_board_context` + a Jinja2 partial)
instead of JSON. The JSON ``/api/...`` contract is unchanged.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Annotated, TypedDict

from fastapi import FastAPI, Form, HTTPException, Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel

from craps_api.board import build_board_context
from craps_api.session_store import SessionNotFoundError, SessionStore
from craps_engine.play import coaching_hint
from craps_engine.registry import snap_to_place_unit
from craps_engine.specs import BetSpec, parse_bet_spec

if TYPE_CHECKING:
    from craps_engine.play import (
        GameView,
        GameViewPayload,
        PlaceOutcomePayload,
        PlayController,
        RollOutcomePayload,
    )

# Package-relative locations of the HTML templates and static assets, resolved
# from this file so they work both under ``uv run pytest`` (source tree) and
# ``uv run craps-web``. Packaging these non-.py files into a wheel is a deploy
# (W6) concern; see the report note.
_PACKAGE_DIR = Path(__file__).parent
_TEMPLATES_DIR = _PACKAGE_DIR / "templates"
_STATIC_DIR = _PACKAGE_DIR / "static"


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


class NewGameRequest(BaseModel):
    """JSON body for ``POST /api/game`` — every field has a sensible default.

    ``max_rolls`` defaults to ``None`` (uncapped), so JSON games run to bust/goal
    like the interactive web games; a programmatic client may still pass an int to
    cap the game at that many rolls.
    """

    seed: int | None = None
    starting_bankroll: int = _DEFAULT_STARTING_BANKROLL
    max_rolls: int | None = None
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


def _render_board(
    templates: Jinja2Templates,
    request: Request,
    *,
    session_id: str,
    view: GameView,
    flash: str = "",
) -> HTMLResponse:
    """Render the ONE ``_board.html`` partial for a live game snapshot.

    Delegates all formatting to the pure :func:`build_board_context` builder and
    computes the coaching hint from the LIVE :class:`GameView` (not the payload),
    so the HTML routes stay thin. Returned as a bare fragment for HTMX swaps. An
    optional ``flash`` (e.g. a bet-refusal message) is surfaced in the board.
    """
    context = build_board_context(
        view.to_dict(),
        session_id=session_id,
        hint=coaching_hint(view),
        flash=flash,
    )
    # Starlette's TemplateResponse wants a plain, mutable ``dict``; a TypedDict is
    # not assignable to ``dict[str, Any]``, so widen it with a shallow copy.
    return templates.TemplateResponse(request, "_board.html", dict(context))


def _place_from_form(
    controller: PlayController,
    *,
    spec: str | None,
    amount: int,
    text: str | None,
) -> str:
    """Funnel a form-submitted bet through the controller; return its notice message.

    The common-bet BUTTONS submit a canonical ``spec`` (``pass``, ``dontpass``,
    ``place 6``, ``take <point>``) plus a shared ``amount`` stake; the free-text
    box submits raw ``text``. Both flow through the controller's own
    ``place_bet_text`` funnel, which NEVER raises — an illegal entry becomes an
    ``ok=false`` outcome whose message is returned here so the caller can flash it
    in the next board render. An empty submission (no spec and no text) returns an
    empty string (nothing placed, nothing to say).
    """
    if text:
        return controller.place_bet_text(text).message
    if spec and spec.strip():
        stake = _snap_place_stake(spec, amount)
        return controller.place_bet_text(f"{spec}:{stake}").message
    return ""


def _snap_place_stake(spec: str, amount: int) -> int:
    """Round a Place-zone button's shared stake to that number's optimal unit.

    The felt places bets from ONE shared stake box, so a raw ``$10`` on the 6
    would pay a fractional ``$11.67``. For a ``place N`` spec, snap the stake to
    the nearest whole multiple of :func:`~craps_engine.registry.place_unit`
    (6/8 -> $6s, 4/5/9/10 -> $5s) so the payout lands in whole dollars. Any
    non-place spec -- or an unparseable one, which the controller will flash as an
    error -- is returned unchanged.
    """
    try:
        parsed = parse_bet_spec(f"{spec}:{amount}")
    except ValueError:
        return amount
    if parsed.kind == "place" and parsed.number is not None:
        return snap_to_place_unit(parsed.number, amount)
    return amount


def create_app() -> FastAPI:  # noqa: C901 (a route-registration factory: each route is a closure over ``store``/``templates``)
    """Build the FastAPI app with its own in-memory :class:`SessionStore`.

    The store is attached to ``app.state`` so it is discoverable/testable and so
    each ``create_app()`` call yields a fully isolated set of games.
    """
    app = FastAPI(title="Craps Play API")
    store = SessionStore()
    app.state.store = store

    templates = Jinja2Templates(directory=str(_TEMPLATES_DIR))
    app.mount("/static", StaticFiles(directory=str(_STATIC_DIR)), name="static")

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

    @app.post("/api/game/{session_id}/bet/{bet_id}/remove", response_model=None)
    def remove_bet(session_id: str, bet_id: str) -> PlaceOutcomePayload:
        """Remove a bet by id; a legal-but-refused removal is still 200 with ``ok=false``.

        Only an unknown SESSION is a 404 — an unknown BET id is handled by the
        controller (``ok=false``), mirroring the placement route's contract.
        """
        return _controller_or_404(store, session_id).remove_bet(bet_id).to_dict()

    @app.post("/api/game/{session_id}/bet/{bet_id}/press", response_model=None)
    def press_bet(session_id: str, bet_id: str) -> PlaceOutcomePayload:
        """Press a just-won bet by id; a refused press is still 200 with ``ok=false``.

        Only an unknown SESSION is a 404 — a refusal (no live bet, nothing won,
        already pressed) is handled by the controller with ``ok=false``.
        """
        return _controller_or_404(store, session_id).press_bet(bet_id).to_dict()

    # --- HTML routes (server-rendered HTMX frontend) ------------------------
    #
    # ``GET /`` serves the new-game FORM plus an empty placeholder board (no
    # auto-created game), so a first visit costs nothing and the seed/stake are
    # chosen up front. Starting a game swaps the placeholder for the real board
    # partial; every subsequent bet/roll swaps that same ``#board`` fragment.
    # Session identity is carried IN THE BOARD HTML via the embedded action URLs
    # (``/game/{id}/bet`` and ``/game/{id}/roll``) — no cookie needed.

    @app.get("/", response_class=HTMLResponse)
    def index(request: Request) -> HTMLResponse:
        """Serve the full page: new-game form + empty placeholder board."""
        return templates.TemplateResponse(request, "index.html", {})

    @app.post("/game", response_class=HTMLResponse)
    def start_game(
        request: Request,
        starting_bankroll: Annotated[int, Form()] = _DEFAULT_STARTING_BANKROLL,
        seed: Annotated[int | None, Form()] = None,
    ) -> HTMLResponse:
        """Create a game from the form and return its come-out board partial.

        The web form intentionally exposes only seed/stake; web games are
        UNCAPPED (``max_rolls`` defaults to ``None``) and run to bust or, if set,
        a win goal. Win-goal and loss-limit fall to the store defaults (the JSON
        ``POST /api/game`` route supports the full knob set for programmatic
        clients).
        """
        session_id, controller = store.create(
            starting_bankroll=starting_bankroll,
            seed=seed,
        )
        return _render_board(templates, request, session_id=session_id, view=controller.snapshot())

    @app.post("/game/{session_id}/bet", response_class=HTMLResponse)
    def place_bet_html(
        request: Request,
        session_id: str,
        spec: Annotated[str | None, Form()] = None,
        amount: Annotated[int, Form()] = 0,
        text: Annotated[str | None, Form()] = None,
    ) -> HTMLResponse:
        """Place a bet (button spec OR free text) and return the board partial.

        The controller's outcome message (a confirmation, or the reason a
        legal-but-refused bet was rejected) is flashed in the board so a refusal
        is visible instead of silently vanishing.
        """
        controller = _controller_or_404(store, session_id)
        flash = _place_from_form(controller, spec=spec, amount=amount, text=text)
        return _render_board(
            templates, request, session_id=session_id, view=controller.snapshot(), flash=flash
        )

    @app.post("/game/{session_id}/remove", response_class=HTMLResponse)
    def remove_bet_html(
        request: Request,
        session_id: str,
        bet_id: Annotated[str, Form()],
    ) -> HTMLResponse:
        """Remove a bet by id and return the board partial (refusal flashed, no 500)."""
        controller = _controller_or_404(store, session_id)
        flash = controller.remove_bet(bet_id).message
        return _render_board(
            templates, request, session_id=session_id, view=controller.snapshot(), flash=flash
        )

    @app.post("/game/{session_id}/press", response_class=HTMLResponse)
    def press_bet_html(
        request: Request,
        session_id: str,
        bet_id: Annotated[str, Form()],
    ) -> HTMLResponse:
        """Press a just-won bet by id and return the board partial (refusal flashed)."""
        controller = _controller_or_404(store, session_id)
        # Felt presses snap the grown Place stake to its unit, mirroring placement.
        flash = controller.press_bet(bet_id, snap_place_to_unit=True).message
        return _render_board(
            templates, request, session_id=session_id, view=controller.snapshot(), flash=flash
        )

    @app.post("/game/{session_id}/roll", response_class=HTMLResponse)
    def roll_html(request: Request, session_id: str) -> HTMLResponse:
        """Roll once and return the updated board partial (404 if unknown id)."""
        controller = _controller_or_404(store, session_id)
        controller.roll()
        return _render_board(templates, request, session_id=session_id, view=controller.snapshot())

    return app
