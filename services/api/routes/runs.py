"""Run lifecycle routes: create, list, inspect, cancel."""

from __future__ import annotations

from fastapi import APIRouter, BackgroundTasks, Request

from repomate_core.contracts import (
    ErrorCode,
    RepositoryInput,
    RunRecord,
    RunStatus,
    TaskSource,
    new_run_id,
)
from repomate_core.orchestration.store_factory import build_store
from repomate_core.safety.url_guard import UnsafeInputError, parse_github_url
from services.api import fair_use
from services.api.config import Settings, read_settings
from services.api.errors import api_error
from services.api.schemas import CancelledResponse, CreateRunRequest, RunCreatedResponse

router = APIRouter(prefix="/api/runs")


@router.post("", status_code=202, response_model=RunCreatedResponse)
async def create_run(
    body: CreateRunRequest, background: BackgroundTasks, request: Request
) -> RunCreatedResponse:
    settings = read_settings()
    store = build_store(settings.runs_root, settings.database_url)
    client_key = fair_use.client_identity(request, settings.trusted_proxies)

    try:
        # Admission covers validation, record creation and dispatch. A
        # rejected submission gets a typed 429 with Retry-After and never
        # creates a run record.
        with fair_use.admission(settings, store, client_key=client_key):
            run_input = _to_run_input(body)
            _validate_urls(run_input)

            run_id = new_run_id()
            store.save_run(
                RunRecord(run_id=run_id, input=run_input, status=RunStatus.PENDING)
            )

            from services.api.dispatch import dispatch_run

            dispatch_run(background, run_input, _pipeline_config(settings), run_id)
    except fair_use.FairUseError as exc:
        raise api_error(
            429,
            ErrorCode.RATE_LIMITED,
            str(exc),
            headers={"Retry-After": str(exc.retry_after)},
        )

    base = f"/api/runs/{run_id}"
    return RunCreatedResponse(
        run_id=run_id,
        status=RunStatus.PENDING,
        links={"run": base, "events": f"{base}/events", "patch": f"{base}/artifacts/patch"},
    )


@router.get("")
def list_runs() -> list[dict]:
    store = build_store(read_settings().runs_root, read_settings().database_url)
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
    record = build_store(read_settings().runs_root, read_settings().database_url).load_run(run_id)
    if record is None:
        raise api_error(404, ErrorCode.INVALID_INPUT, f"unknown run: {run_id}")
    return record


@router.post("/{run_id}/cancel", status_code=202, response_model=CancelledResponse)
def cancel_run(run_id: str) -> CancelledResponse:
    store = build_store(read_settings().runs_root, read_settings().database_url)
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
        database_url=settings.database_url,
        github_token=settings.github_token,
        keep_workspace=settings.keep_workspace,
        max_run_seconds=settings.max_run_seconds,
        sandbox_enabled=settings.sandbox_enabled,
    )
