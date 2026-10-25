"""FastAPI application factory."""

from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from services.api.config import read_settings
from services.api.routes import artifacts, events, health, metrics, runs

APP_VERSION = "0.1.0"


@asynccontextmanager
async def _lifespan(app: FastAPI):
    _sweep_stale_workspaces()
    yield


def _sweep_stale_workspaces() -> None:
    import os

    from repomate_core.orchestration.store_factory import build_store

    hours = float(os.environ.get("REPOMATE_SWEEP_HOURS", "24"))
    settings = read_settings()
    store = build_store(settings.runs_root, settings.database_url)
    removed = store.sweep_stale_workspaces(max_age_hours=hours)
    if removed:
        app.state.swept_runs = removed  # surfaced via /api/metrics debugging


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
