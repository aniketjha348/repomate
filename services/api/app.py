"""FastAPI application factory."""

from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from repomate_core.env import load_env_file, loaded_env_file
from services.api.config import read_settings
from services.api.routes import artifacts, events, health, metrics, runs

APP_VERSION = "0.1.0"

# Configuration is environment-driven and the README tells operators to keep
# it in ``.env``, so read that file before anything (including this module's
# own ``read_settings()`` calls) consults the environment. Exported variables
# still win, and ``REPOMATE_SKIP_DOTENV=1`` disables the file entirely.
load_env_file()


@asynccontextmanager
async def _lifespan(app: FastAPI):
    app.state.env_file = loaded_env_file() or ""
    _sweep_stale_workspaces(app)
    _reconcile_stale_runs(app)
    yield


def _sweep_stale_workspaces(app: FastAPI) -> None:
    import os

    from repomate_core.orchestration.store_factory import build_store

    hours = float(os.environ.get("REPOMATE_SWEEP_HOURS", "24"))
    settings = read_settings()
    store = build_store(settings.runs_root, settings.database_url)
    removed = store.sweep_stale_workspaces(max_age_hours=hours)
    if removed:
        app.state.swept_runs = removed  # surfaced via /api/metrics debugging


def _reconcile_stale_runs(app: FastAPI) -> None:
    """Close out runs left RUNNING by a previous process.

    In-process execution (the default) cannot survive a restart: a run that
    was mid-flight when the server stopped would otherwise report RUNNING
    forever, and the UI would poll a run that will never move. Anything
    still RUNNING/PENDING at startup is therefore marked FAILED with an
    explicit reason — an honest terminal state beats a permanent lie.
    """
    import os

    from repomate_core.orchestration.store_factory import build_store

    if os.environ.get("REPOMATE_RECONCILE_STALE_RUNS", "1") != "1":
        return
    settings = read_settings()
    store = build_store(settings.runs_root, settings.database_url)
    reconciled = store.reconcile_stale_runs()
    if reconciled:
        app.state.reconciled_runs = reconciled  # surfaced via /api/metrics


def create_app() -> FastAPI:
    app = FastAPI(title="RepoMate API", version=APP_VERSION, lifespan=_lifespan)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=read_settings().cors_origins,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.include_router(health.router)
    app.include_router(runs.router)
    app.include_router(artifacts.router)
    app.include_router(events.router)
    app.include_router(metrics.router)
    return app
