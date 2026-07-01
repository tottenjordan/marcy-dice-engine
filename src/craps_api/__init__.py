"""Thin FastAPI JSON backend over the pure ``craps_engine`` play controller.

This is the ONLY package where web dependencies (FastAPI/uvicorn) and HTTP I/O
live. It wraps :class:`craps_engine.play.PlayController` behind a JSON API with an
in-memory session store; all game logic stays in the pure engine. ``craps_api``
imports ``craps_engine`` and never the reverse.
"""
