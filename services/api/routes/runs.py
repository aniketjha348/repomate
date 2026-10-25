"""Run lifecycle routes: create, list, inspect, cancel."""

from __future__ import annotations

import asyncio

from fastapi import APIRouter, BackgroundTasks

from repomate_core.contracts import (
    ErrorCode,
    RepositoryInput,
    RunRecord,
    RunStatus,
    TaskSource,
    new_run_id,
)
from repomate_core.orchestration.pipeline import run_pipeline
from repomate_core.orchestration.store import RunStore
from repomate_core.safety.url_guard import UnsafeInputError, parse_github_url
from services.api.config import Settings, read_settings
from services.api.errors import api_error
from services.api.schemas import CancelledResponse, CreateRunRequest, RunCreatedResponse

router = APIRouter(prefix="/api/runs")


@router.post("", status_code=202, response_model=RunCreatedResponse)
async def create_run(body: CreateRunRequest, background: BackgroundTasks) -> RunCreatedResponse:
    run_input = _to_run_input(body)
    _validate_urls(run_input)

    settings = read_settings()
    store = RunStore(settings.runs_root)
    run_id = new_run_id()
    store.save_run(RunRecord(run_id=run_id, input=run_input, status=RunStatus.PENDING))

    background.add_task(
        asyncio.to_thread, run_pipeline, run_input,
        config=_pipeline_config(settings), run_id=run_id,
    )

    base = f"/api/runs/{run_id}"
    return RunCreatedResponse(
        run_id=run_id,
        status=RunStatus.PENDING,
        links={"run": base, "events": f"{base}/events", "patch": f"{base}/artifacts/patch"},
    )


@router.get("")
def list_runs() -> list[dict]:
    store = RunStore(read_settings().runs_root)
    summaries = []
    for run_id in store.list_run_ids()[-50:]:
        record = store.load_run(run_id)
        if record:
            summaries.append(
                {
                    "run_id": run_id,
                    "status": record.status,
                    "created_at": record.created_at,
                    "planner": record.planner,
                }
            )
    return summaries


@router.get("/{run_id}")
def get_run(run_id: str) -> RunRecord:
    record = RunStore(read_settings().runs_root).load_run(run_id)
    if record is None:
        raise api_error(404, ErrorCode.INVALID_INPUT, f"unknown run: {run_id}")
    return record


@router.post("/{run_id}/cancel", status_code=202, response_model=CancelledResponse)
def cancel_run(run_id: str) -> CancelledResponse:
    store = RunStore(read_settings().runs_root)
    if store.load_run(run_id) is None:
        raise api_error(404, ErrorCode.INVALID_INPUT, f"unknown run: {run_id}")
    if not store.cancel_requested(run_id):
        store.request_cancel(run_id)
    return CancelledResponse(run_id=run_id, cancelled=True)


def _to_run_input(body: CreateRunRequest) -> RepositoryInput:
    if body.issue_url:
        return RepositoryInput(source=TaskSource.GITHUB_ISSUE, issue_url=body.issue_url.strip())
    if body.repo_url and body.task and body.task.strip():
        return RepositoryInput(
            source=TaskSource.REPO_TASK,
            repo_url=body.repo_url.strip(),
            task=body.task.strip(),
        )
    raise api_error(
        422, ErrorCode.INVALID_INPUT,
        "provide either issue_url, or repo_url plus task",
    )


def _validate_urls(run_input: RepositoryInput) -> None:
    raw = (
        run_input.issue_url
        if run_input.source is TaskSource.GITHUB_ISSUE
        else run_input.repo_url
    ) or ""
    try:
        parse_github_url(raw)
    except UnsafeInputError as exc:
        raise api_error(400, ErrorCode.INVALID_INPUT, str(exc))


def _pipeline_config(settings: Settings):
    from repomate_core.orchestration.pipeline_config import PipelineConfig

    return PipelineConfig(
        runs_root=settings.runs_root,
        github_token=settings.github_token,
        keep_workspace=settings.keep_workspace,
        max_run_seconds=settings.max_run_seconds,
    )
