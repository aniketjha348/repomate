"""Liveness and configuration identity."""

from __future__ import annotations

import os

from fastapi import APIRouter

from repomate_core.orchestration.pipeline import resolve_planner

router = APIRouter()


@router.get("/api/health")
def health() -> dict:
    import os

    model_configured = bool(
        os.environ.get("OPENAI_API_KEY", "").strip()
        or os.environ.get("VYCE_API_KEY", "").strip()
    )
    return {
        "status": "ok",
        "planner": resolve_planner().name,
        "model_configured": model_configured,
    }
