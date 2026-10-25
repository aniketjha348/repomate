"""Verification runner.

Honesty rules (product-level contract):

- ``PASSED``/``FAILED`` may only come from a check that actually ran —
  a real subprocess with a captured exit code, or a deterministic policy
  evaluation over the artifact bytes.
- ``NOT_RUN`` requires an explicit human-readable reason. The MVP does not
  execute repository test suites: untrusted commands only ever run inside
  the Phase 4 disposable sandbox, so until that lands the check is
  reported as ``NOT_RUN`` — never silently skipped, never faked.
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

_OUTPUT_TAIL = 800


def run_verification(
    ws: RepoWorkspace,
    artifact: ContributionArtifact,
    policy: PatchPolicy,
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

    # 3) Repository test suite — deliberately not executed yet.
    checks.append(
        VerificationCheck(
            name="repository-test-suite",
            command=None,
            status=VerificationStatus.NOT_RUN,
            reason=(
                "Untrusted repository commands require the Phase 4 disposable "
                "execution sandbox (CPU/memory/time-limited worker); they are "
                "never executed on the API host."
            ),
        )
    )

    return VerificationReceipt(
        checks=checks,
        overall=_overall(checks),
        environment=f"in-process verifier on {platform.system()}/{platform.machine()} (Phase 4 sandbox pending)",
        limitations=[
            "Test-suite execution lands with the Phase 4 sandbox; patch-level checks only.",
            "Verification runs on the orchestrator host, not an isolated worker.",
        ],
    )


def _overall(checks: list[VerificationCheck]) -> VerificationStatus:
    statuses = {check.status for check in checks}
    if VerificationStatus.FAILED in statuses:
        return VerificationStatus.FAILED
    if VerificationStatus.PASSED in statuses:
        return VerificationStatus.PASSED
    return VerificationStatus.NOT_RUN
