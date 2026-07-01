# Deployable image for the craps FastAPI + HTMX web app (`craps-web`).
#
# WHY RUN FROM SOURCE (not a built wheel): a built wheel packages only the
# `craps_engine` module — it does NOT contain `craps_api`/`craps_tui` nor the
# `craps_api/templates/` and `craps_api/static/` data files. So instead of
# building + pip-installing a wheel, we copy the project in and run `uv sync`,
# which does an editable-style install that exposes ALL of `src/` (and its data
# files) at runtime. The app is then launched with `uv run craps-web`.
#
# Networking: `craps_api.runner:main` binds `HOST`/`PORT` from the environment
# (defaulting to 127.0.0.1:8000 for local dev). We set HOST=0.0.0.0 so the app
# is reachable via published ports. Cloud Run and similar hosts inject their own
# PORT, which the runner honors — no image change needed for those platforms.

# Pinned slim Python base (project requires >=3.11); uv is copied in below.
FROM python:3.11-slim-bookworm

# uv, pinned to the version this project's lockfile was produced with.
COPY --from=ghcr.io/astral-sh/uv:0.9.14 /uv /uvx /bin/

# Byte-compile on install and copy (not link) packages into the venv, which is
# the recommended behavior for a self-contained container image. UV_NO_SYNC keeps
# the runtime `uv run craps-web` from re-syncing the default groups (dev/test/ui)
# back into the venv on container start — without it, `uv run` would auto-install
# pytest/ruff/ty/textual at boot and undo the lean `--no-default-groups` install.
ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_NO_SYNC=1

WORKDIR /app

# Copy the lockfile + project metadata first so the dependency layer caches and
# only re-resolves when these change. README.md is referenced by [project.readme]
# and is required for the install to resolve.
COPY pyproject.toml uv.lock README.md ./

# Copy the source tree (the editable install points here at runtime).
COPY src ./src

# Install ONLY the `web` group (fastapi/uvicorn/jinja2/python-multipart) plus the
# project itself — nothing else. `--no-default-groups` drops the dev-time groups
# (`dev`, `test`, `ui`) that `pyproject.toml` syncs by default, so pytest, ruff,
# ty, and textual stay OUT of the runtime image. This still performs the
# editable-style install that exposes ALL of `src/` (and its data files) at
# runtime. The uv cache mount keeps a source-only rebuild from re-resolving deps.
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --no-default-groups --group web --frozen

# Run as an unprivileged user.
RUN useradd --create-home --uid 10001 appuser \
    && chown -R appuser:appuser /app
USER appuser

# Bind to all interfaces inside the container so published ports are reachable.
# PORT is set for clarity; hosts that inject their own PORT (e.g. Cloud Run)
# override it and the runner honors that.
ENV HOST=0.0.0.0 \
    PORT=8000

EXPOSE 8000

# Launch the web app from the synced source tree (see rationale above).
CMD ["uv", "run", "craps-web"]
