"""Verification runner.

Honesty rules (product-level contract):

- ``PASSED``/``FAILED`` may only come from a check that actually ran —
  a real subprocess with a captured exit code, or a deterministic policy
  evaluation over the artifact bytes.
- ``NOT_RUN`` requires an explicit human-readable reason.

Baseline vs post-patch: the selected repository check is executed twice, in
two separate checkouts of the same pinned commit. The baseline checkout is
clean; the patched checkout has the validated patch applied. Both runs use the
same detected command, sandbox limits and scrubbed environment. The comparison
is classified from the two statuses and commands only — no model judgment.

Egress isolation: the sandbox denies network access by default and the
boundary is proven by an adversarial probe that runs real connection attempts
from inside the sandbox. A suite that cannot be isolated is ``NOT_RUN``, and
the receipt records the policy under ``sandbox``.
"""

from __future__ import annotations

import hashlib
import platform
import tempfile
from pathlib import Path
from typing import Literal

from repomate_core.artifacts.patch import PatchPolicy, validate_patch
from repomate_core.contracts import (
    ContributionArtifact,
    SandboxPolicyRecord,
    VerificationCheck,
    VerificationComparison,
    VerificationReceipt,
    VerificationRunRecord,
    VerificationStatus,
    classify_comparison_outcome,
    comparison_interpretation,
)
from repomate_core.repository.workspace import RepoWorkspace
from repomate_core.verification.network_policy import (
    NetworkPolicy,
    network_policy_record,
    resolve_network_policy,
)
from repomate_core.verification.sandbox import (
    SandboxLimits,
    ToolchainCommand,
    detect_test_command,
    run_egress_probe_check,
    run_test_suite_check,
    sandbox_environment_description,
    sandbox_limitations,
)

_OUTPUT_TAIL = 800


def run_verification(
    ws: RepoWorkspace,
    artifact: ContributionArtifact,
    policy: PatchPolicy,
    *,
    sandbox_enabled: bool = True,
    limits: SandboxLimits | None = None,
    network_policy: NetworkPolicy | None = None,
) -> VerificationReceipt:
    checks: list[VerificationCheck] = []
    active_policy = network_policy or resolve_network_policy()

    # The receipt binds the comparison to the actual pinned commit and patch
    # bytes, not to a model's description of them.
    ws.reset_hard()
    base_commit = ws.commit_sha
    patch_sha256 = hashlib.sha256(artifact.patch.encode("utf-8")).hexdigest()

    # 1) Deterministic policy evaluation over the patch text.
    violations = validate_patch(artifact.patch, policy)
    checks.append(
        VerificationCheck(
            name="patch-path-policy",
            command="internal:patch-policy",
            status=VerificationStatus.FAILED if violations else VerificationStatus.PASSED,
            reason="; ".join(violations),
        )
    )

    # 2) Run the same selected check in two independent, equivalent checkouts:
    #    a clean baseline and a patched tree. The temporary directory is
    #    removed after the receipt data has been copied out.
    with tempfile.TemporaryDirectory(prefix="repomate-verify-") as temp_dir:
        temp_root = Path(temp_dir)
        baseline_ws, baseline_error = _clone_workspace(
            ws, temp_root / "baseline", base_commit
        )
        patched_ws, patched_error = _clone_workspace(
            ws, temp_root / "patched", base_commit
        )

        apply_check, patch_applied = _check_and_apply_patch(
            patched_ws, artifact.patch, patched_error
        )
        checks.append(apply_check)

        # 3) Prove the sandbox boundary before trusting it with untrusted code.
        #    This runs real connection attempts from inside the sandbox; the
        #    receipt may only claim egress_validation PASSED because of it.
        egress_check = run_egress_probe_check(limits=limits, policy=active_policy)
        checks.append(egress_check)

        # Detect once from the clean baseline so the patched run cannot change
        # which command is selected (for example by adding a manifest).
        command = (
            detect_test_command(baseline_ws) if baseline_ws is not None else None
        )

        baseline_check = _baseline_check(
            baseline_ws,
            baseline_error,
            command=command,
            sandbox_enabled=sandbox_enabled,
            limits=limits,
            policy=active_policy,
        )
        post_check = _post_patch_check(
            baseline_ws,
            baseline_error,
            patched_ws,
            patched_error,
            patch_applied=patch_applied,
            command=command,
            sandbox_enabled=sandbox_enabled,
            limits=limits,
            policy=active_policy,
        )
        checks.append(post_check)

        baseline_run = _to_run_record("baseline", base_commit, baseline_check)
        post_run = _to_run_record("post_patch", base_commit, post_check)
        comparison = _build_comparison(
            base_commit, patch_sha256, baseline_run, post_run
        )

    ws.reset_hard()

    return VerificationReceipt(
        checks=checks,
        overall=_overall(checks),
        environment=(
            f"{sandbox_environment_description(active_policy)} "
            f"on {platform.system()}/{platform.machine()}"
        ),
        limitations=sandbox_limitations(active_policy),
        sandbox=SandboxPolicyRecord(
            **network_policy_record(
                active_policy,
                egress_validation=egress_check.status.value,
                egress_detail=egress_check.reason,
            )
        ),
        base_commit=base_commit,
        patch_sha256=patch_sha256,
        comparison=comparison,
    )


def _clone_workspace(
    source: RepoWorkspace, dest: Path, expected_commit: str
) -> tuple[RepoWorkspace | None, str]:
    """Clone a pinned equivalent workspace, or return an explicit reason."""
    try:
        clone = source.clone_to(dest)
        if clone.commit_sha != expected_commit:
            raise RuntimeError(
                f"clone is at {clone.commit_sha}, expected {expected_commit}"
            )
        return clone, ""
    except Exception as exc:  # a clone failure is an incomplete comparison
        return None, f"{type(exc).__name__}: {exc}"[:_OUTPUT_TAIL]


def _check_and_apply_patch(
    patched_ws: RepoWorkspace | None,
    patch: str,
    patched_error: str,
) -> tuple[VerificationCheck, bool]:
    if patched_ws is None:
        return (
            VerificationCheck(
                name="patch-applies-on-pinned-commit",
                command="git apply --check",
                status=VerificationStatus.NOT_RUN,
                reason=(
                    "patched workspace could not be created, so the patch could "
                    f"not be checked: {patched_error}"
                ),
            ),
            False,
        )

    ok, exit_code, stderr = patched_ws.apply_check(patch)
    check = VerificationCheck(
        name="patch-applies-on-pinned-commit",
        command="git apply --check",
        status=VerificationStatus.PASSED if ok else VerificationStatus.FAILED,
        exit_code=exit_code,
        output_tail=stderr[:_OUTPUT_TAIL],
    )
    if not ok:
        return check, False

    try:
        patched_ws.apply(patch)
    except Exception as exc:
        return (
            check.model_copy(
                update={
                    "status": VerificationStatus.FAILED,
                    "reason": (
                        "git apply failed after --check succeeded: "
                        f"{type(exc).__name__}: {exc}"
                    )[:_OUTPUT_TAIL],
                }
            ),
            False,
        )
    return check, True


def _baseline_check(
    baseline_ws: RepoWorkspace | None,
    baseline_error: str,
    *,
    command: ToolchainCommand | None,
    sandbox_enabled: bool,
    limits: SandboxLimits | None,
    policy: NetworkPolicy | None,
) -> VerificationCheck:
    if baseline_ws is None:
        return VerificationCheck(
            name="repository-test-suite",
            command=None,
            status=VerificationStatus.NOT_RUN,
            reason=(
                "baseline workspace could not be created, so no before/after "
                f"comparison can be made: {baseline_error}"
            ),
        )
    return _test_suite_check(
        baseline_ws,
        sandbox_enabled=sandbox_enabled,
        limits=limits,
        policy=policy,
        command=command,
    )


def _post_patch_check(
    baseline_ws: RepoWorkspace | None,
    baseline_error: str,
    patched_ws: RepoWorkspace | None,
    patched_error: str,
    *,
    patch_applied: bool,
    command: ToolchainCommand | None,
    sandbox_enabled: bool,
    limits: SandboxLimits | None,
    policy: NetworkPolicy | None,
) -> VerificationCheck:
    if baseline_ws is None:
        return VerificationCheck(
            name="repository-test-suite",
            command=None,
            status=VerificationStatus.NOT_RUN,
            reason=(
                "the baseline workspace was unavailable, so the post-patch run "
                "was not started without a comparable baseline: "
                f"{baseline_error}"
            ),
        )
    if patched_ws is None:
        return VerificationCheck(
            name="repository-test-suite",
            command=None,
            status=VerificationStatus.NOT_RUN,
            reason=(
                "patched workspace could not be created, so the post-patch "
                f"check was not run: {patched_error}"
            ),
        )
    if not patch_applied:
        return VerificationCheck(
            name="repository-test-suite",
            command=command.display if command else None,
            status=VerificationStatus.NOT_RUN,
            reason=(
                "the patch did not apply to the patched workspace, so the "
                "post-patch check was not run"
            ),
        )
    return _test_suite_check(
        patched_ws,
        sandbox_enabled=sandbox_enabled,
        limits=limits,
        policy=policy,
        command=command,
    )


def _test_suite_check(
    ws: RepoWorkspace,
    *,
    sandbox_enabled: bool,
    limits: SandboxLimits | None,
    policy: NetworkPolicy | None = None,
    command: ToolchainCommand | None = None,
) -> VerificationCheck:
    if not sandbox_enabled:
        return VerificationCheck(
            name="repository-test-suite",
            command=None,
            status=VerificationStatus.NOT_RUN,
            reason="sandbox execution disabled by REPOMATE_SANDBOX_ENABLED configuration",
        )
    return run_test_suite_check(ws, limits=limits, policy=policy, command=command)


def _to_run_record(
    phase: Literal["baseline", "post_patch"], commit: str, check: VerificationCheck
) -> VerificationRunRecord:
    return VerificationRunRecord(
        phase=phase,
        commit_sha=commit,
        command=check.command,
        status=check.status,
        exit_code=check.exit_code,
        duration_ms=check.duration_ms,
        output_summary=check.output_tail,
        reason=check.reason,
    )


def _build_comparison(
    base_commit: str,
    patch_sha256: str,
    baseline: VerificationRunRecord,
    post_patch: VerificationRunRecord,
) -> VerificationComparison:
    outcome = classify_comparison_outcome(baseline.status, post_patch.status)
    return VerificationComparison(
        base_commit=base_commit,
        patch_sha256=patch_sha256,
        baseline=baseline,
        post_patch=post_patch,
        outcome=outcome,
        interpretation=comparison_interpretation(outcome),
    )


def _overall(checks: list[VerificationCheck]) -> VerificationStatus:
    statuses = {check.status for check in checks}
    if VerificationStatus.FAILED in statuses:
        return VerificationStatus.FAILED
    if VerificationStatus.PASSED in statuses:
        return VerificationStatus.PASSED
    return VerificationStatus.NOT_RUN
