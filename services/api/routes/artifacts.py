"""Artifact listing and download routes (store-agnostic).

The primary diff and the supplementary markdown documents are listed through
one endpoint so a reviewer does not have to guess which files a run produced.
Downloads are attachment responses: plans are never rendered as HTML by the
API.
"""

from __future__ import annotations

from fastapi import APIRouter, Response

from repomate_core.contracts import ArtifactKind, ErrorCode, RunRecord
from repomate_core.orchestration.store_factory import build_store
from services.api.config import read_settings
from services.api.errors import api_error

router = APIRouter(prefix="/api/runs/{run_id}/artifacts")


def _load_record(run_id: str) -> RunRecord:
    store = build_store(read_settings().runs_root, read_settings().database_url)
    record = store.load_run(run_id)
    if record is None:
        raise api_error(404, ErrorCode.INVALID_INPUT, f"unknown run: {run_id}")
    return record


def _patch_name(kind: ArtifactKind) -> str:
    if kind is ArtifactKind.DOCS_DIFF:
        return "documentation.patch"
    if kind is ArtifactKind.TEST_DIFF:
        return "tests.patch"
    return "contribution.patch"


@router.get("")
def list_artifacts(run_id: str) -> list[dict]:
    """List every downloadable artifact for a run with its kind and size."""
    record = _load_record(run_id)
    items: list[dict] = []
    if record.artifact is not None:
        artifact = record.artifact
        items.append(
            {
                "name": _patch_name(artifact.kind),
                "kind": artifact.kind.value,
                "media_type": "text/x-diff; charset=utf-8",
                "size_bytes": len(artifact.patch.encode("utf-8")),
                "download_url": f"/api/runs/{run_id}/artifacts/patch",
            }
        )
    for document in record.documents:
        items.append(
            {
                "name": document.name,
                "kind": document.kind.value,
                "media_type": document.media_type,
                "size_bytes": len(document.content.encode("utf-8")),
                "download_url": f"/api/runs/{run_id}/artifacts/{document.name}",
            }
        )
    return items


@router.get("/patch")
def download_patch(run_id: str) -> Response:
    record = _load_record(run_id)
    artifact = record.artifact
    if artifact is None:
        raise api_error(404, ErrorCode.INVALID_INPUT, f"no patch for run: {run_id}")
    return Response(
        content=artifact.patch,
        media_type="text/x-diff; charset=utf-8",
        headers={
            "Content-Disposition": f'attachment; filename="{_patch_name(artifact.kind)}"',
            "X-Content-Type-Options": "nosniff",
        },
    )


@router.get("/{name}")
def download_document(run_id: str, name: str) -> Response:
    record = _load_record(run_id)
    document = next((item for item in record.documents if item.name == name), None)
    if document is None:
        raise api_error(404, ErrorCode.INVALID_INPUT, f"no artifact {name!r} for run: {run_id}")
    return Response(
        content=document.content,
        media_type=document.media_type,
        headers={
            "Content-Disposition": f'attachment; filename="{document.name}"',
            "X-Content-Type-Options": "nosniff",
        },
    )
