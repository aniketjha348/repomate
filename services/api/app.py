"""FastAPI application factory."""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from services.api.config import read_settings
from services.api.routes import artifacts, events, health, runs

APP_VERSION = "0.1.0"


def create_app() -> FastAPI:
    app = FastAPI(title="RepoMate API", version=APP_VERSION)
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
    return app
