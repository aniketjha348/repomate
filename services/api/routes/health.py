"""Liveness and configuration identity."""

from __future__ import annotations

from fastapi import APIRouter

from repomate_core.env import loaded_env_file
from repomate_core.models import provider_from_env
from repomate_core.orchestration.pipeline import resolve_planner

router = APIRouter()


@router.get("/api/health")
def health() -> dict:
    # Ask the provider factory rather than re-reading the key: one source of
    # truth for whether an Ollama model is configured.
    model_configured = provider_from_env() is not None
    return {
        "status": "ok",
        "planner": resolve_planner().name,
        "model_configured": model_configured,
        # Which ``.env`` (if any) this process loaded — so "why is my planner
        # heuristic?" has a visible answer instead of a silent downgrade.
        "env_file": loaded_env_file() or "",
    }
