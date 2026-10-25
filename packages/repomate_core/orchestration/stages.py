"""Stage implementations for the contribution pipeline.

Each stage receives the shared :class:`RunContext` (plus its inputs),
emits its own progress events, and returns what the next stage needs.
Guards (cancellation + deadline) are checked by the pipeline between
stages.
"""

from __future__ import annotations

from typing import Callable, Optional

from repomate_core.artifacts.generator import generate_docs_artifact
from repomate_core.contracts import (
    ContributionArtifact,
    ContributionPlan,
    ErrorCode,
    EvidenceRecord,
    GitHubIssue,
    RepositoryInput,
    RepositorySnapshot,
    StageName,
    TaskSource,
    VerificationReceipt,
)
from repomate_core.evidence.collector import collect_evidence
from repomate_core.orchestration.context import RunContext
from repomate_core.orchestration.errors import PipelineError
from repomate_core.orchestration.pipeline_config import PipelineConfig
from repomate_core.planning.heuristic import HeuristicPlanner
from repomate_core.repository.github import fetch_issue
from repomate_core.repository.inspect import inspect_repository
from repomate_core.repository.workspace import RepoWorkspace
from repomate_core.safety.url_guard import GitHubRef
from repomate_core.verification.runner import run_verification

WorkspaceFactory = Callable[[GitHubRef, object, PipelineConfig], RepoWorkspace]


def stage_pin_snapshot(
    ctx: RunContext,
    ref: GitHubRef,
    workspace_factory: WorkspaceFactory,
) -> RepoWorkspace:
    ctx.emit(StageName.PIN_SNAPSHOT, "STARTED", f"Cloning {ref.slug} (shallow, pinned to HEAD)")
    workspace = workspace_factory(ref, ctx.workspace_dir, ctx.config)
    snapshot: RepositorySnapshot = inspect_repository(
        workspace, owner=ref.owner, name=ref.repo, url=ref.repo_url
    )
    ctx.record.snapshot = snapshot
    ctx.emit(
        StageName.PIN_SNAPSHOT,
        "COMPLETED",
        f"Pinned {ref.slug}@{snapshot.commit_sha[:10]} "
        f"(license: {snapshot.license.status.value}, {snapshot.file_count} files)",
    )
    return workspace


def stage_retrieve_evidence(
    ctx: RunContext, ref: GitHubRef, run_input: RepositoryInput, workspace: RepoWorkspace
) -> tuple[str, list[EvidenceRecord]]:
    """Returns (task_text, evidence)."""
    ctx.emit(StageName.RETRIEVE_EVIDENCE, "STARTED", "Collecting issue and repository evidence")
    issue: Optional[GitHubIssue] = None
    task_text = run_input.task or ""
    if run_input.source is TaskSource.GITHUB_ISSUE:
        issue = fetch_issue(ref, token=ctx.config.github_token)
        ctx.record.issue = issue
        task_text = f"{issue.title}\n\n{issue.body}"
        ctx.emit(
            StageName.RETRIEVE_EVIDENCE, "INFO",
            f"Fetched issue #{issue.number}: {issue.title[:80]}",
        )

    evidence = collect_evidence(workspace, ctx.record.snapshot, task_text, issue)
    ctx.record.evidence = evidence
    ctx.emit(
        StageName.RETRIEVE_EVIDENCE,
        "COMPLETED",
        f"Collected {len(evidence)} evidence record(s)"
        + ("" if evidence else " — none matched the task"),
    )
    return task_text, evidence


def stage_plan(
    ctx: RunContext, task_text: str, evidence: list[EvidenceRecord]
) -> ContributionPlan:
    from repomate_core.orchestration.pipeline import resolve_planner

    ctx.emit(StageName.PLAN, "STARTED", "Building contribution plan from evidence")
    planner = ctx.config.planner or resolve_planner()
    ctx.record.planner = planner.name
    plan = planner.plan(task_text, ctx.record.snapshot, evidence)
    ctx.record.plan = plan
    ctx.emit(
        StageName.PLAN,
        "COMPLETED",
        f"Plan ({plan.task_type.value}) by {planner.name}: {plan.summary[:100]}"
        + (" — needs more info" if plan.need_more_info else ""),
    )
    return plan


def stage_generate_artifact(
    ctx: RunContext,
    workspace: RepoWorkspace,
    plan: ContributionPlan,
    task_text: str,
    evidence: list[EvidenceRecord],
) -> ContributionArtifact:
    ctx.emit(StageName.GENERATE_ARTIFACT, "STARTED", "Generating documentation artifact")
    if plan.task_type.value != "DOCUMENTATION":
        raise PipelineError(
            ErrorCode.UNSUPPORTED_INPUT,
            f"artifact generation for {plan.task_type.value} tasks is not enabled in the MVP",
        )
    artifact = generate_docs_artifact(workspace, plan, task_text, evidence)
    ctx.record.artifact = artifact
    ctx.emit(
        StageName.GENERATE_ARTIFACT,
        "COMPLETED",
        f"Generated {artifact.kind.value} touching {', '.join(artifact.affected_paths)}",
    )
    return artifact


def stage_verify(
    ctx: RunContext, workspace: RepoWorkspace, artifact: ContributionArtifact
) -> tuple[VerificationReceipt, list[str]]:
    """Returns (receipt, failed_artifact_checks).

    Only artifact-level failures (patch policy / patch application) fail
    the run. A failing repository test suite is an honest receipt
    outcome — the environment or the repository is broken, not the
    artifact — so the run completes and the receipt carries the FAILED
    check with its captured output.
    """
    from repomate_core.artifacts.patch import DOCS_PATCH_POLICY

    ctx.emit(StageName.VERIFY, "STARTED", "Running verification checks")
    receipt = run_verification(
        workspace, artifact, DOCS_PATCH_POLICY, sandbox_enabled=ctx.config.sandbox_enabled
    )
    ctx.record.receipt = receipt
    failed = [
        check.name
        for check in receipt.checks
        if check.status.value == "FAILED" and check.name != "repository-test-suite"
    ]
    suite = next((c for c in receipt.checks if c.name == "repository-test-suite"), None)
    if suite is not None and suite.status.value == "FAILED":
        ctx.emit(
            StageName.VERIFY, "INFO",
            f"Repository test suite FAILED (exit {suite.exit_code}); "
            "run completes with an honest receipt",
        )
    ctx.emit(
        StageName.VERIFY,
        "COMPLETED" if not failed else "FAILED",
        f"Verification overall: {receipt.overall.value}"
        + (f" (failed: {', '.join(failed)})" if failed else ""),
    )
    return receipt, failed


def plan_for_missing_evidence(
    ctx: RunContext, task_text: str
) -> ContributionPlan:
    """Honest NEED_MORE_INFO plan when nothing matched the task."""
    return HeuristicPlanner().plan(task_text, ctx.record.snapshot or _empty_snapshot(ctx), [])


def _empty_snapshot(ctx: RunContext) -> RepositorySnapshot:  # pragma: no cover
    raise PipelineError(ErrorCode.INTERNAL, "snapshot missing before evidence stage")
