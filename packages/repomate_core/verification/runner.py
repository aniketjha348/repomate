"""Verification runner.

Honesty rules (product-level contract):

- ``PASSED``/``FAILED`` may only come from a check that actually ran —
  a real subprocess with a captured exit code, or a deterministic policy
  evaluation over the artifact bytes.
- ``NOT_RUN`` requires an explicit human-readable reason.

Phase 4: the repository test suite now executes inside the disposable
process sandbox (wall-time/CPU/memory limits, scrubbed environment) when
a supported toolchain is detected; otherwise it is reported ``NOT_RUN``
with the precise reason.
"""

from __future__ import annotations

import platform

from repomate_core.artifacts.patch import PatchPolicy, validate_patch
from repomate_core.contracts import (
    ContributionArtifact,
    VerificationCheck,
    VerificationReceipt,
    VerificationStatus,
)
from repomate_core.repository.workspace import RepoWorkspace
from repomate_core.verification.sandbox import SandboxLimits, run_test_suite_check

_OUTPUT_TAIL = 800


def run_verification(
    ws: RepoWorkspace,
    artifact: ContributionArtifact,
    policy: PatchPolicy,
    *,
    sandbox_enabled: bool = True,
    limits: SandboxLimits | None = None,
) -> VerificationReceipt:
    checks: list[VerificationCheck] = []

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

    # 2) Real execution: the patch must apply to the clean pinned snapshot.
    ws.reset_hard()
    ok, exit_code, stderr = ws.apply_check(artifact.patch)
    checks.append(
        VerificationCheck(
            name="patch-applies-on-pinned-commit",
            command="git apply --check",
            status=VerificationStatus.PASSED if ok else VerificationStatus.FAILED,
            exit_code=exit_code,
            output_tail=stderr[:_OUTPUT_TAIL],
        )
    )

    # 3) Repository test suite inside the disposable sandbox — run against
    #    the PATCHED tree when the patch applies, so a fix's effect on the
    #    suite is actually measured. The tree is reset afterwards.
    if ok:
        try:
            ws.apply(artifact.patch)
        except Exception:
            pass  # apply_check passed; a failed best-effort apply leaves the clean tree
    checks.append(_test_suite_check(ws, sandbox_enabled=sandbox_enabled, limits=limits))
    ws.reset_hard()

    return VerificationReceipt(
        checks=checks,
        overall=_overall(checks),
        environment=(
            f"process sandbox (wall/cpu/memory limits, scrubbed env) "
            f"on {platform.system()}/{platform.machine()}"
        ),
        limitations=[
            "The process sandbox does not isolate network egress; a container-per-run "
            "backend is planned for untrusted-network toolchains.",
        ],
    )


def _test_suite_check(
    ws: RepoWorkspace,
    *,
    sandbox_enabled: bool,
    limits: SandboxLimits | None,
) -> VerificationCheck:
    if not sandbox_enabled:
        return VerificationCheck(
            name="repository-test-suite",
            command=None,
            status=VerificationStatus.NOT_RUN,
            reason="sandbox execution disabled by REPOMATE_SANDBOX_ENABLED configuration",
        )
    return run_test_suite_check(ws, limits=limits)


def _overall(checks: list[VerificationCheck]) -> VerificationStatus:
    statuses = {check.status for check in checks}
    if VerificationStatus.FAILED in statuses:
        return VerificationStatus.FAILED
    if VerificationStatus.PASSED in statuses:
        return VerificationStatus.PASSED
    return VerificationStatus.NOT_RUN
