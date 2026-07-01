# /// script
# requires-python = ">=3.11"
# dependencies = [
#     "playwright",
#     "uvicorn",
#     "fastapi",
#     "jinja2",
#     "python-multipart",
# ]
# ///
"""Capture deterministic screenshots of the craps web felt for the README.

This is a standalone PEP 723 script: Playwright is an INLINE, script-only
dependency and is deliberately NOT a project dependency (see ``pyproject.toml``),
so the quality gate and tests never import it. The FastAPI app is booted
in-process on a fixed port under a background uvicorn thread and driven headless
with Chromium, using a FIXED SEED so the dice — and therefore every captured
board — are byte-for-byte reproducible across re-runs.

Run recipe
----------
One-time (installs the headless Chromium browser Playwright drives)::

    uv run --with playwright playwright install chromium

Capture (writes the four PNGs under ``docs/images/``)::

    uv run --script docs/capture_screenshots.py

Because the script runs under ``uv run --script`` it does not see the project
venv, so the project's ``src/`` is prepended to ``sys.path`` and the app's own
runtime deps (uvicorn/fastapi/jinja2/python-multipart) ride along in the inline
dependency block above.

The five captured states (each is a locator screenshot of the ``#board``
element, so the full board is captured even when it is taller than the viewport):

1. ``felt-comeout.png``  — a fresh game (empty felt, come-out phase).
2. ``felt-bets.png``     — after placing bets (chips + a non-$0 "At risk" badge):
   Pass Line + Place 6 + Place 8.
3. ``felt-postroll.png`` — after a roll (dice + per-roll net indicator +
   last-10 roll strip + Net %).
4. ``felt-odds.png``     — with a point ON: the yellow point ring + "ON" puck on
   the point's box AND the Take/Lay free-odds zones all visible.
5. ``felt-comeodds.png`` — a Come bet travelled to its come-point with free odds
   behind it: the come-odds chip on the come-point's box PLUS the ``+ odds`` and
   ``Come-out: OFF`` row controls (a SECOND game on its own fixed seed).

Captures 1-4 share one game on ``_SEED``; capture 5 starts a fresh game on
``_COMEODDS_SEED`` (whose first two rolls deterministically set a point and then
travel a Come bet to a different come-point without a seven-out).

The viewport is intentionally WIDE (>= 1024px) so the Phase-6 no-scroll
dashboard layout (``@media (min-width: 1024px)`` in ``static/style.css``) is the
active layout being documented.
"""

from __future__ import annotations

import sys
import threading
import time
from pathlib import Path
from urllib.error import URLError
from urllib.request import urlopen

# Prepend the project's src/ so craps_api / craps_engine import under uv --script.
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_PROJECT_ROOT / "src"))

import uvicorn  # noqa: E402 — after sys.path shim so the inline dep resolves.
from playwright.sync_api import Page, sync_playwright  # noqa: E402

from craps_api.app import create_app  # noqa: E402

# Fixed knobs keep every capture reproducible. Seed 4 establishes point 5 on the
# very first roll (verified: seed-4 first-roll totals are 5, 7, 8, ...), so once
# felt-postroll's roll lands the point is ON and felt-odds reliably shows the
# yellow point ring + "ON" puck on box 5 alongside the Take/Lay odds zones.
_HOST = "127.0.0.1"
_PORT = 8099
_SEED = 4
# Seed 7's first rolls are 5, 10, ...: roll 1 sets point 5, then a Come bet placed
# after it travels to come-point 10 on roll 2 (no seven-out), so the come-odds
# capture is byte-for-byte reproducible.
_COMEODDS_SEED = 7
_STARTING_BANKROLL = 1000
_BASE_URL = f"http://{_HOST}:{_PORT}"
# Wide viewport (>= 1024px) so the Phase-6 no-scroll dashboard media query is the
# active layout. The #board locator screenshot still captures the full element
# even if it is taller than this viewport height.
_VIEWPORT = {"width": 1280, "height": 800}
_IMAGES_DIR = _PROJECT_ROOT / "docs" / "images"

# HTMX-swap settle time: the board is replaced via outerHTML after each POST, so
# give the swap a beat before screenshotting.
_SWAP_SETTLE_MS = 300

# The HTTP status an up server returns from the index page.
_HTTP_OK = 200


def _serve() -> threading.Thread:
    """Boot the app under uvicorn on a daemon thread; return the running thread."""
    server = uvicorn.Server(
        uvicorn.Config(create_app(), host=_HOST, port=_PORT, log_level="warning")
    )
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    return thread


def _wait_until_up(timeout_s: float = 15.0) -> None:
    """Poll the index page until the server answers (or raise on timeout)."""
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        try:
            with urlopen(f"{_BASE_URL}/", timeout=1) as resp:  # noqa: S310 — fixed localhost URL.
                if resp.status == _HTTP_OK:
                    return
        except (URLError, ConnectionError, OSError):
            time.sleep(0.1)
    msg = f"server did not come up on {_BASE_URL} within {timeout_s}s"
    raise RuntimeError(msg)


def _start_game(page: Page, *, seed: int = _SEED) -> None:
    """Fill and submit the new-game form with a fixed ``seed`` + stake."""
    page.goto(_BASE_URL, wait_until="networkidle")
    page.fill('input[name="seed"]', str(seed))
    page.fill('input[name="starting_bankroll"]', str(_STARTING_BANKROLL))
    page.click('form.new-game button[type="submit"]')
    page.wait_for_selector("#board .felt", state="visible")
    page.wait_for_timeout(_SWAP_SETTLE_MS)


def _place_zone(page: Page, spec: str) -> None:
    """Click a playable felt zone by its canonical spec (e.g. ``pass``, ``place 6``)."""
    page.click(f'button[hx-vals*=\'"spec": "{spec}"\']')
    page.wait_for_timeout(_SWAP_SETTLE_MS)


def _roll(page: Page) -> None:
    """Click the roll button and let the board swap settle."""
    page.click("form.roll button.roll-btn")
    page.wait_for_timeout(_SWAP_SETTLE_MS)


def _shot(page: Page, name: str) -> Path:
    """Screenshot the current board into ``docs/images/<name>`` and return the path."""
    path = _IMAGES_DIR / name
    page.locator("#board").screenshot(path=str(path))
    return path


def _capture(page: Page) -> list[Path]:
    """Drive the four HTMX flows and write the four board PNGs; return their paths."""
    written: list[Path] = []

    # 1. Fresh come-out board (empty felt).
    _start_game(page)
    written.append(_shot(page, "felt-comeout.png"))

    # 2. After placing a couple of bets (chips on zones + a non-$0 "At risk" badge).
    _place_zone(page, "pass")
    _place_zone(page, "place 6")
    _place_zone(page, "place 8")
    written.append(_shot(page, "felt-bets.png"))

    # 3. After a roll (dice + per-roll net indicator + last-10 roll strip + Net %).
    _roll(page)
    written.append(_shot(page, "felt-postroll.png"))

    # 4. Point ON so the yellow point ring + "ON" puck AND the Take/Lay odds zones
    #    render. Seed 4 sets point 5 on the first roll, so the point is already ON
    #    after step 3's roll; keep rolling defensively until the take-odds zone
    #    appears (bounded), then assert a point really is established.
    for _ in range(20):
        if page.locator('button[hx-vals*=\'"spec": "take\']').count() > 0:
            break
        _roll(page)
    take = page.locator('button[hx-vals*=\'"spec": "take\']').first
    if take.count() == 0 or page.locator(".point-puck").count() == 0:
        msg = "no point established — felt-odds would miss the ring/puck + odds zones"
        raise RuntimeError(msg)
    # Best-effort tooltip nudge: hover the Take Odds zone so its title fires. Native
    # title tooltips may not render in a screenshot; the odds zone being visible is
    # the real goal, so this is non-blocking.
    take.hover()
    page.wait_for_timeout(_SWAP_SETTLE_MS)
    written.append(_shot(page, "felt-odds.png"))

    # 5. Come-odds: a SECOND game. Establish a point, drop a Come bet, roll it to a
    #    different come-point, then back it with free odds so the come-odds chip
    #    lands on that box and the "+ odds" / "Come-out: OFF" row controls render.
    written.append(_capture_come_odds(page))

    return written


def _capture_come_odds(page: Page) -> Path:
    """Drive a fresh game to a Come bet + come-odds and screenshot it."""
    _start_game(page, seed=_COMEODDS_SEED)
    _roll(page)  # roll 1 = 5 -> point 5 established
    _place_zone(page, "come")  # a Come bet (still coming)
    _roll(page)  # roll 2 = 10 -> the Come bet travels to come-point 10 (puck stays 5)

    # The travelled Come row now offers "+ odds" (posts a take-odds spec on 10).
    add_odds = page.locator('button.bet-odds[hx-vals*=\'"spec": "take 10"\']')
    if add_odds.count() == 0:
        msg = "come bet did not travel to 10 — the come-odds '+ odds' control is missing"
        raise RuntimeError(msg)
    add_odds.first.click()
    page.wait_for_timeout(_SWAP_SETTLE_MS)

    # Sanity-check the come-odds chip + come-out toggle actually rendered.
    if page.locator(".chip-odds").count() == 0 or page.locator("button.bet-comeout").count() == 0:
        msg = "come-odds chip or come-out toggle missing — felt-comeodds would be wrong"
        raise RuntimeError(msg)
    return _shot(page, "felt-comeodds.png")


def main() -> None:
    """Boot the app, capture the four felt screenshots, and print a summary."""
    _IMAGES_DIR.mkdir(parents=True, exist_ok=True)
    _serve()
    _wait_until_up()

    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        try:
            page = browser.new_page(viewport=_VIEWPORT)
            written = _capture(page)
        finally:
            browser.close()

    print(f"Wrote {len(written)} screenshots (seed={_SEED}) to {_IMAGES_DIR}:")  # noqa: T201
    for path in written:
        size = path.stat().st_size
        print(f"  {path.name}  ({size} bytes)")  # noqa: T201


if __name__ == "__main__":
    main()
