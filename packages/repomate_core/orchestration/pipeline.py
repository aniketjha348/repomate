"""The end-to-end contribution pipeline.

    validate input -> pin snapshot -> retrieve evidence -> plan
    -> generate artifact -> verify -> publish

Guarantees enforced here (docs/security.md): every run is bound to an
exact commit before analysis starts; no evidence => ``NEED_MORE_INFO``,
never a forced change; a wall-clock budget and cooperative cancellation
are checked between stages; all failures map to typed ``ErrorCode``
values — the API never leaks stack traces to clients.

Stage bodies live in :mod:`repomate_core.orchestration.stages`; this
module owns flow, error mapping and finalization.
"""

from __future__ import annotations

from pathlib import Path
from typing import Callable, Optional

from repomate_core.contracts import (
    ErrorCode,
    RepositoryInput,
    RetrievalStatus,
    RunRecord,
    RunStatus,
    StageName,
    TaskSource,
    ToolLoopStatus,
)
from repomate_core.models import ModelBudgetExceeded, ModelError, ModelTimeoutError
from repomate_core.orchestration.context import EventCallback, RunContext
from repomate_core.orchestration.errors import PipelineError, RunCancelled
from repomate_core.orchestration.pipeline_config import PipelineConfig
from repomate_core.orchestration.stages import (
    WorkspaceFactory,
    plan_for_missing_evidence,
    stage_expand_evidence,
    stage_generate_artifact,
    stage_plan,
    stage_pin_snapshot,
    stage_retrieve_evidence,
    stage_validate_grounding,
    stage_verify,
)
from repomate_core.planning.heuristic import HeuristicPlanner
from repomate_core.planning.model_planner import ModelPlanner
from repomate_core.planning.types import Planner
from repomate_core.repository.errors import (
    GitHubAccessError,
    RateLimitedError,
    WorkspaceError,
)
from repomate_core.repository.workspace import RepoWorkspace
from repomate_core.safety.url_guard import GitHubRef, UnsafeInputError, parse_github_url


def github_workspace_factory(
    ref: GitHubRef, dest: Path, config: PipelineConfig
) -> RepoWorkspace:
    """Default workspace source: a shallow clone pinned to HEAD."""
    return RepoWorkspace.from_github(ref, dest, token=config.github_token)


def resolve_planner() -> Planner:
    from repomate_core.models import provider_from_env

    provider = provider_from_env()
    if provider is not None:
        return ModelPlanner(provider)
    return HeuristicPlanner()


def run_pipeline(
    run_input: RepositoryInput,
    *,
    config: Optional[PipelineConfig] = None,
    run_id: Optional[str] = None,
    event_cb: Optional[EventCallback] = None,
    workspace_factory: Optional[WorkspaceFactory] = None,
) -> RunRecord:
    ctx = RunContext.create(
        run_input, config or PipelineConfig(), run_id=run_id, event_cb=event_cb
    )
    factory = workspace_factory or github_workspace_factory
    try:
        _run_stages(ctx, run_input, factory)
    except Exception as exc:
        _fail(ctx, exc)
    return ctx.record


def _run_stages(
    ctx: RunContext, run_input: RepositoryInput, factory: WorkspaceFactory
) -> None:
    # 1) validate ------------------------------------------------------------
    ctx.emit(StageName.VALIDATE_INPUT, "STARTED", "Validating task input")
    ref = _validate_input(run_input)
    ctx.emit(
        StageName.VALIDATE_INPUT,
        "COMPLETED",
        f"Input accepted: {ref.slug}"
        + (f" issue #{ref.issue_number}" if ref.issue_number else ""),
    )
    ctx.guard()

    # 2) pin --------------------------------------------------------------------
    workspace = stage_pin_snapshot(ctx, ref, factory)
    ctx.guard()

    # 3) evidence -----------------------------------------------------------------
    task_text, evidence = stage_retrieve_evidence(ctx, ref, run_input, workspace)
    ctx.guard()

    retrieval = ctx.record.retrieval
    if retrieval is not None and retrieval.status is RetrievalStatus.PARTIAL:
        # A truncated scan is never allowed to continue as if it were a full
        # analysis. The run publishes its evidence, orientation and the
        # remaining-work report, but stops before planning or generating an
        # artifact from an explicitly incomplete repository scope.
        ctx.record.status = RunStatus.PARTIAL
        ctx.emit(
            StageName.RETRIEVE_EVIDENCE,
            "INFO",
            "Retrieval limits reached; run marked PARTIAL without claiming "
            "full analysis",
        )
        return _finish(ctx)

    # 4) supplementary model-driven retrieval (bounded) --------------------------
    # The model may ask for extra context through three typed read-only tools.
    # Every retrieved item is re-validated against the pinned workspace, and a
    # global tool-budget hit is an explicit PARTIAL stop.
    planner = ctx.config.planner or resolve_planner()
    ctx.record.planner = planner.name
    evidence = stage_expand_evidence(ctx, workspace, task_text, evidence, planner)
    ctx.guard()

    tool_loop = ctx.record.tool_loop
    if tool_loop is not None and tool_loop.status is ToolLoopStatus.PARTIAL:
        ctx.record.status = RunStatus.PARTIAL
        ctx.emit(
            StageName.RETRIEVE_EVIDENCE,
            "INFO",
            "Tool-retrieval limits reached; run marked PARTIAL without "
            "claiming full analysis",
        )
        return _finish(ctx)

    if not evidence:
        ctx.record.plan = plan_for_missing_evidence(ctx, task_text)
        ctx.record.status = RunStatus.NEED_MORE_INFO
        ctx.emit(
            StageName.PLAN, "INFO",
            "No evidence located; returning NEED_MORE_INFO without touching the repository",
        )
        return _finish(ctx)

    # 5) plan ------------------------------------------------------------------------
    plan = stage_plan(ctx, task_text, evidence, planner)
    ctx.guard()

    # 4b) grounding ----------------------------------------------------------------
    # Citations are validated against this run's evidence before any
    # artifact is generated, and before the run can stop early: a plan that
    # asks for more information still makes assertions, and those
    # assertions must not reach a report unvalidated.
    stage_validate_grounding(ctx, plan, evidence, workspace)
    ctx.guard()

    if plan.need_more_info:
        ctx.record.status = RunStatus.NEED_MORE_INFO
        return _finish(ctx)

    # 5) artifact ---------------------------------------------------------------------
    stage_generate_artifact(ctx, workspace, plan, task_text, evidence)
    ctx.guard()

    # 6) verify ------------------------------------------------------------------------
    _receipt, failed = stage_verify(ctx, workspace, ctx.record.artifact)
    if failed:
        ctx.record.status = RunStatus.FAILED
        ctx.record.error = PipelineError(
            ErrorCode.INTERNAL,
            "verification rejected the generated patch",
            detail="; ".join(failed),
        ).to_run_error()
        return _finish(ctx)
    ctx.guard()

    # 7) publish ------------------------------------------------------------------------
    ctx.emit(StageName.PUBLISH, "STARTED", "Publishing run record and artifacts")
    ctx.record.status = RunStatus.COMPLETED
    _finish(ctx)
    ctx.emit(StageName.PUBLISH, "COMPLETED", f"Run {ctx.record.run_id} completed")


def _validate_input(run_input: RepositoryInput) -> GitHubRef:
    try:
        if run_input.source is TaskSource.GITHUB_ISSUE:
            return parse_github_url(run_input.issue_url or "")
        return parse_github_url(run_input.repo_url or "")
    except UnsafeInputError as exc:
        raise PipelineError(ErrorCode.INVALID_INPUT, str(exc)) from exc


def _finish(ctx: RunContext) -> None:
    ctx.cleanup_workspace()
    ctx.persist()


def _fail(ctx: RunContext, exc: Exception) -> None:
    if isinstance(exc, RunCancelled):
        ctx.record.status = RunStatus.CANCELLED
        ctx.emit(None, "INFO", "Run cancelled by request")
    else:
        ctx.record.status = RunStatus.FAILED
        ctx.record.error = _to_run_error(exc)
        code = ctx.record.error.code.value
        ctx.emit(None, "FAILED", f"{code}: {ctx.record.error.message}")
    _finish(ctx)


def _to_run_error(exc: Exception):
    from repomate_core.contracts import RunError

    if isinstance(exc, PipelineError):
        return exc.to_run_error()
    if isinstance(exc, ModelBudgetExceeded):
        return RunError(code=ErrorCode.BUDGET_EXCEEDED, message=str(exc))
    if isinstance(exc, (ModelError, ModelTimeoutError)):
        return RunError(code=ErrorCode.MODEL, message=str(exc))
    if type(exc).__name__ == "SoftTimeLimitExceeded":
        # Celery's soft time limit is matched by name so the core package
        # stays celery-free. The run is finalised FAILED/TIMEOUT instead of
        # being mislabelled as an internal error.
        return RunError(
            code=ErrorCode.TIMEOUT,
            message="worker run time limit exceeded",
            detail=(
                "The execution worker's soft time limit interrupted the run. "
                "No verification result is claimed."
            ),
        )
    if isinstance(exc, RateLimitedError):
        return RunError(code=ErrorCode.RATE_LIMITED, message=str(exc))
    if isinstance(exc, (GitHubAccessError, WorkspaceError, OSError)):
        return RunError(code=ErrorCode.NETWORK, message=str(exc))
    return RunError(
        code=ErrorCode.INTERNAL,
        message=f"unexpected failure: {type(exc).__name__}: {exc}"[:500],
    )
