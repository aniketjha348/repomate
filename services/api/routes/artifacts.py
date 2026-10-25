"""Artifact download routes."""

from __future__ import annotations

from fastapi import APIRouter
from fastapi.responses import FileResponse

from repomate_core.contracts import ErrorCode
from repomate_core.orchestration.store import RunStore
from services.api.config import read_settings
from services.api.errors import api_error

router = APIRouter(prefix="/api/runs/{run_id}/artifacts")


@router.get("/patch")
def download_patch(run_id: str):
    path = RunStore(read_settings().runs_root).artifact_path(run_id)
    if path is None:
        raise api_error(404, ErrorCode.INVALID_INPUT, f"no artifact for run: {run_id}")
    return FileResponse(
        path, media_type="text/x-diff; charset=utf-8", filename=f"{run_id}.patch"
    )
