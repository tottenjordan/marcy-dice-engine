"""Console entry point for the craps web API (``craps-web``).

This is the uvicorn boot glue — the web analogue of the TUI's Textual entry
point. It only wires :func:`create_app` to a uvicorn server; all app behavior is
tested via ``TestClient`` against ``create_app``.
"""

from __future__ import annotations

import os

import uvicorn

from craps_api.app import create_app


def main() -> None:  # pragma: no cover - uvicorn boot glue, mirrors the TUI entry
    """Serve the web app via uvicorn, honoring HOST/PORT env overrides.

    Defaults to ``127.0.0.1:8000`` for local dev (unchanged). A container sets
    ``HOST=0.0.0.0`` so the app is reachable via published ports; Cloud Run and
    similar hosts inject their own ``PORT``, which is honored here.
    """
    host = os.environ.get("HOST", "127.0.0.1")
    port = int(os.environ.get("PORT", "8000"))
    uvicorn.run(create_app(), host=host, port=port)


if __name__ == "__main__":  # pragma: no cover - module-as-script guard
    main()
