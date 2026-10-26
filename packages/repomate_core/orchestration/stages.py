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
    ArtifactKind,
    ContributionArtifact,
    ContributionPlan,
    ErrorCode,
    EvidenceRecord,
    GitHubIssue,
    GroundingReport,
    RepositoryInput,
    RepositorySnapshot,
    RetrievalStatus,
    StageName,
    TaskSource,
    TaskType,
    ToolLoopStatus,
    VerificationReceipt,
)
from repomate_core.evidence.collector import collect_evidence_with_report
from repomate_core.insights import build_orientation, build_test_guidance
from repomate_core.orchestration.context import RunContext
from repomate_core.orchestration.errors import PipelineError
from repomate_core.orchestration.pipeline_config import PipelineConfig
from repomate_core.planning.heuristic import HeuristicPlanner
from repomate_core.planning.types import Planner
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

    evidence = collect_evidence_with_report(
        workspace,
        ctx.record.snapshot,
        task_text,
        issue,
        limits=ctx.config.retrieval_limits,
    )
    ctx.record.evidence = evidence.records
    ctx.record.retrieval = evidence.report
    ctx.emit(
        StageName.RETRIEVE_EVIDENCE,
        "COMPLETED",
        f"Collected {len(evidence.records)} evidence record(s)"
        + ("" if evidence.records else " — none matched the task"),
    )
    if evidence.report.status is RetrievalStatus.PARTIAL:
        ctx.emit(StageName.RETRIEVE_EVIDENCE, "INFO", evidence.report.summary)

    # Newcomer orientation + which-tests-to-run guidance (PS04 background):
    # deterministic, snapshot/evidence-derived, never overstated.
    ctx.record.orientation = build_orientation(
        workspace, ctx.record.snapshot, evidence.records
    )
    ctx.record.test_guidance = build_test_guidance(
        workspace, ctx.record.snapshot, evidence.records
    )
    return task_text, evidence.records


def stage_expand_evidence(
    ctx: RunContext,
    workspace: RepoWorkspace,
    task_text: str,
    evidence: list[EvidenceRecord],
    planner: Planner,
) -> list[EvidenceRecord]:
    """Let a model planner request bounded supplementary context.

    Only the typed ``search_text``/``read_file``/``inspect_manifest`` tools
    are available, every file item is re-validated against the pinned
    workspace, and a global tool-budget hit returns ``PARTIAL`` rather than
    pretending the extra context was examined. Heuristic runs skip this
    stage entirely.
    """
    from repomate_core.evidence.tools import run_tool_loop
    from repomate_core.planning.model_planner import ModelPlanner

    if not isinstance(planner, ModelPlanner):
        return evidence

    planner.bind_runtime(
        budget=ctx.model_budget,
        guard=ctx.guard,
        remaining_seconds=ctx.remaining_seconds,
    )
    ctx.emit(
        StageName.RETRIEVE_EVIDENCE,
        "STARTED",
        "Running bounded model tool loop for supplementary context",
    )
    outcome = run_tool_loop(
        workspace,
        ctx.record.snapshot or _empty_snapshot(ctx),
        task_text,
        planner.provider,
        evidence,
        ctx.config.tool_limits,
        budget=ctx.model_budget,
        guard=ctx.guard,
        remaining_seconds=ctx.remaining_seconds,
    )
    ctx.record.tool_loop = outcome.report
    merged = _merge_evidence(evidence, outcome.records)
    ctx.record.evidence = merged

    # Rebuild the deterministic newcomer views from the combined evidence.
    ctx.record.orientation = build_orientation(
        workspace, ctx.record.snapshot or _empty_snapshot(ctx), merged
    )
    ctx.record.test_guidance = build_test_guidance(
        workspace, ctx.record.snapshot or _empty_snapshot(ctx), merged
    )

    status = "COMPLETED" if outcome.report.status is ToolLoopStatus.COMPLETE else "INFO"
    ctx.emit(
        StageName.RETRIEVE_EVIDENCE,
        status,
        f"Tool retrieval {outcome.report.status.value}: "
        f"{outcome.report.tool_calls} tool call(s), "
        f"{outcome.report.records_added} validated record(s) added"
        + (
            f" — {outcome.report.stop_reason}"
            if outcome.report.stop_reason not in ("", "model_done")
            else ""
        ),
    )
    if outcome.report.status is ToolLoopStatus.PARTIAL:
        ctx.emit(StageName.RETRIEVE_EVIDENCE, "INFO", outcome.report.summary)
    return merged


def _merge_evidence(
    initial: list[EvidenceRecord], extra: list[EvidenceRecord]
) -> list[EvidenceRecord]:
    """De-duplicate and re-number evidence in deterministic order.

    The collector and the tool loop both assign temporary ids; plans are
    produced after this merge, so re-numbering here cannot invalidate a
    citation. Initial evidence stays first, which keeps ids stable for the
    common (no-tool) case.
    """
    merged: list[EvidenceRecord] = []
    seen: set[tuple] = set()
    for record in [*initial, *extra]:
        key = (
            record.path,
            record.start_line,
            record.end_line,
            record.snippet,
        )
        if key in seen:
            continue
        seen.add(key)
        merged.append(record.model_copy(update={"id": f"ev{len(merged) + 1}"}))
    return merged


def stage_validate_grounding(
    ctx: RunContext,
    plan: ContributionPlan,
    evidence: list[EvidenceRecord],
    workspace: RepoWorkspace,
) -> GroundingReport:
    """Validate every citation in the plan against this run's evidence.

    This is the enforcement half of the evidence-first contract: a claim
    whose citations do not resolve (or do not relate to it) is recorded as
    a hypothesis, and the warning is persisted with the run so a report can
    never present an unresolved reference as a verified citation.
    """
    from repomate_core.evidence.grounding import validate_plan_grounding

    ctx.emit(StageName.PLAN, "STARTED", "Validating plan citations against evidence")
    snapshot = ctx.record.snapshot or _empty_snapshot(ctx)
    report = validate_plan_grounding(plan, evidence, snapshot, workspace=workspace)
    ctx.record.grounding = report

    unresolved = report.unresolved_evidence_ids
    ctx.emit(
        StageName.PLAN,
        "INFO" if not unresolved else "FAILED",
        f"Grounding: {report.supported_claims} supported / "
        f"{report.hypothesis_claims} hypothesis claim(s), "
        f"{len(report.resolved_evidence_ids)} resolved citation(s)"
        + (f", {len(unresolved)} unresolved: {', '.join(unresolved[:5])}" if unresolved else ""),
    )
    return report


def stage_plan(
    ctx: RunContext,
    task_text: str,
    evidence: list[EvidenceRecord],
    planner: Optional[Planner] = None,
) -> ContributionPlan:
    from repomate_core.orchestration.pipeline import resolve_planner

    ctx.emit(StageName.PLAN, "STARTED", "Building contribution plan from evidence")
    planner = planner or ctx.config.planner or resolve_planner()
    ctx.record.planner = planner.name
    plan = planner.plan(task_text, ctx.record.snapshot, evidence)
    ctx.record.plan = plan
    ctx.record.planner = plan.planned_by
    if ctx.record.tool_loop is not None:
        loop = ctx.record.tool_loop
        if loop.stop_reason == "invalid_model_output":
            plan.limitations.append(
                "model tool loop stopped on an invalid tool call; additional "
                "repository context may be missing"
            )
        if loop.rejected_items:
            plan.limitations.append(
                f"{loop.rejected_items} retrieved item(s) were rejected by "
                "evidence validation and were not used in this plan"
            )
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
    ctx.emit(StageName.GENERATE_ARTIFACT, "STARTED", "Generating contribution artifact")
    if plan.task_type.value == "DOCUMENTATION":
        artifact = generate_docs_artifact(workspace, plan, task_text, evidence)
    elif plan.proposed_edits:
        # Model-proposed search/replace edits: bug fixes, tests, small
        # features — anything expressible as anchored edits.
        from repomate_core.artifacts.codefix import EditAnchorError, apply_proposed_edits

        try:
            artifact = apply_proposed_edits(workspace, plan)
        except EditAnchorError as exc:
            raise PipelineError(
                ErrorCode.MODEL,
                "model edit did not anchor to the pinned snapshot",
                detail=str(exc),
            ) from exc
        # The diff is the same anchored format; the kind records the task the
        # contribution answers. TEST tasks are downloadable as TEST_DIFF.
        if plan.task_type is TaskType.TEST:
            artifact = artifact.model_copy(update={"kind": ArtifactKind.TEST_DIFF})
    else:
        raise PipelineError(
            ErrorCode.UNSUPPORTED_INPUT,
            f"artifact generation for {plan.task_type.value} tasks requires "
            "model-proposed edits; the heuristic planner supports documentation only",
        )
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

    The selected repository check runs once against a clean baseline
    checkout and once against a separate patched checkout. The receipt
    records the deterministic comparison; a successful patched run alone is
    never presented as proof that the issue is resolved.
    """
    from repomate_core.artifacts.patch import (
        CODE_FIX_PATCH_POLICY,
        DOCS_PATCH_POLICY,
        TEST_PATCH_POLICY,
    )

    ctx.emit(StageName.VERIFY, "STARTED", "Running verification checks")
    if artifact.kind is ArtifactKind.DOCS_DIFF:
        policy = DOCS_PATCH_POLICY
    elif artifact.kind is ArtifactKind.TEST_DIFF:
        policy = TEST_PATCH_POLICY
    else:
        policy = CODE_FIX_PATCH_POLICY
    receipt = run_verification(
        workspace, artifact, policy, sandbox_enabled=ctx.config.sandbox_enabled
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
    if receipt.comparison is not None:
        comparison = receipt.comparison
        ctx.emit(
            StageName.VERIFY,
            "INFO",
            f"Baseline {comparison.baseline.status.value} -> post-patch "
            f"{comparison.post_patch.status.value}: {comparison.outcome.value}",
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
    planner = HeuristicPlanner()
    # Attribute the run even when the pipeline stops before ``stage_plan``.
    ctx.record.planner = planner.name
    return planner.plan(task_text, ctx.record.snapshot or _empty_snapshot(ctx), [])


def _empty_snapshot(ctx: RunContext) -> RepositorySnapshot:  # pragma: no cover
    raise PipelineError(ErrorCode.INTERNAL, "snapshot missing before evidence stage")
