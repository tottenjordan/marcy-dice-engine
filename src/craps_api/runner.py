"""Console entry point for the craps web API (``craps-web``).

This is the uvicorn boot glue — the web analogue of the TUI's Textual entry
point. It only wires :func:`create_app` to a uvicorn server; all app behavior is
tested via ``TestClient`` against ``create_app``.
"""

from __future__ import annotations

import uvicorn

from craps_api.app import create_app


def main() -> None:  # pragma: no cover - uvicorn boot glue, mirrors the TUI entry
    """Serve the JSON API on 127.0.0.1:8000 via uvicorn."""
    uvicorn.run(create_app(), host="127.0.0.1", port=8000)


if __name__ == "__main__":  # pragma: no cover - module-as-script guard
    main()
