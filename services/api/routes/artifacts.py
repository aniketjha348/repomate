"""Artifact download routes (store-agnostic)."""

from __future__ import annotations

from fastapi import APIRouter, Response

from repomate_core.contracts import ErrorCode
from repomate_core.orchestration.store_factory import build_store
from services.api.config import read_settings
from services.api.errors import api_error

router = APIRouter(prefix="/api/runs/{run_id}/artifacts")


@router.get("/patch")
def download_patch(run_id: str) -> Response:
    store = build_store(read_settings().runs_root, read_settings().database_url)
    patch = store.read_artifact(run_id)
    if patch is None:
        raise api_error(404, ErrorCode.INVALID_INPUT, f"no artifact for run: {run_id}")
    return Response(
        content=patch,
        media_type="text/x-diff; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{run_id}.patch"'},
    )
