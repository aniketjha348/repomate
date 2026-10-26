"""Verification checks and the aggregated receipt.

Honesty contract: ``PASSED``/``FAILED`` may only originate from real
execution or deterministic evaluation; ``NOT_RUN`` requires a reason.

Baseline contract: when a repository check executes, it runs against a clean
checkout of the pinned commit *and* against a separate checkout with the
validated patch applied. The comparison outcome is classified from those two
statuses and the exact command they executed -- never from model judgment.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, computed_field, model_validator

from repomate_core.contracts._time import utcnow
from repomate_core.contracts.enums import ComparisonOutcome, VerificationStatus


class VerificationCheck(BaseModel):
    name: str
    command: str | None = None
    status: VerificationStatus
    exit_code: int | None = None
    duration_ms: int | None = Field(default=None, ge=0)
    output_tail: str = Field(default="", max_length=2000)
    reason: str = ""

    @model_validator(mode="after")
    def _check_not_run_reason(self) -> "VerificationCheck":
        if self.status is VerificationStatus.NOT_RUN and not self.reason.strip():
            raise ValueError("NOT_RUN checks must carry an explicit reason")
        return self


class SandboxPolicyRecord(BaseModel):
    """Receipt record of the execution sandbox's network policy."""

    network_mode: str
    backend: str
    policy_enforced: bool
    egress_validation: str
    egress_detail: str = ""


class VerificationRunRecord(BaseModel):
    """One side of the baseline/post-patch comparison.

    ``command`` is the exact display command handed to the sandbox;
    ``exit_code`` and ``output_summary`` are captured from that execution.
    A ``NOT_RUN`` record always carries the reason it did not execute.
    """

    phase: Literal["baseline", "post_patch"]
    commit_sha: str = Field(min_length=1)
    command: str | None = None
    status: VerificationStatus
    exit_code: int | None = None
    duration_ms: int | None = Field(default=None, ge=0)
    output_summary: str = Field(default="", max_length=2000)
    reason: str = ""

    @model_validator(mode="after")
    def _run_not_run_reason(self) -> "VerificationRunRecord":
        if self.status is VerificationStatus.NOT_RUN and not self.reason.strip():
            raise ValueError("NOT_RUN verification runs must carry an explicit reason")
        return self


class VerificationComparison(BaseModel):
    """Deterministic result of comparing baseline and patched executions."""

    base_commit: str = Field(min_length=1)
    patch_sha256: str = Field(min_length=64, max_length=64)
    baseline: VerificationRunRecord
    post_patch: VerificationRunRecord
    outcome: ComparisonOutcome
    interpretation: str = Field(min_length=1)

    @computed_field  # type: ignore[prop-decorator]
    @property
    def commands_match(self) -> bool | None:
        """Whether both runs executed the same exact command.

        ``None`` means no command was selected. ``False`` is reserved for an
        incomplete comparison in which only one side executed.
        """
        if self.baseline.command and self.post_patch.command:
            return self.baseline.command == self.post_patch.command
        if self.baseline.command or self.post_patch.command:
            return False
        return None

    @model_validator(mode="after")
    def _comparison_is_consistent(self) -> "VerificationComparison":
        if self.baseline.phase != "baseline":
            raise ValueError("baseline record must use phase='baseline'")
        if self.post_patch.phase != "post_patch":
            raise ValueError("post-patch record must use phase='post_patch'")
        for run in (self.baseline, self.post_patch):
            if run.commit_sha != self.base_commit:
                raise ValueError("both verification runs must be pinned to the base commit")

        both_executed = (
            self.baseline.status is not VerificationStatus.NOT_RUN
            and self.post_patch.status is not VerificationStatus.NOT_RUN
        )
        if both_executed:
            if not self.baseline.command or not self.post_patch.command:
                raise ValueError("executed comparisons must record the exact command")
            if self.baseline.command != self.post_patch.command:
                raise ValueError(
                    "baseline and post-patch runs must execute the same exact command"
                )

        expected = classify_comparison_outcome(
            self.baseline.status, self.post_patch.status
        )
        if self.outcome is not expected:
            raise ValueError(
                f"outcome {self.outcome.value} does not match the run statuses "
                f"(baseline={self.baseline.status.value}, "
                f"post_patch={self.post_patch.status.value}); expected {expected.value}"
            )
        if self.interpretation != comparison_interpretation(expected):
            raise ValueError("interpretation must be the deterministic text for the outcome")
        return self


_COMPARISON_INTERPRETATIONS: dict[ComparisonOutcome, str] = {
    ComparisonOutcome.CONSISTENT_IMPROVEMENT: (
        "the selected check failed on the clean baseline commit and passed "
        "after applying the patch; consistent improvement, not final proof of "
        "correctness"
    ),
    ComparisonOutcome.NO_REGRESSION_DETECTED: (
        "the selected check passed before and after the patch; no regression "
        "was detected in the selected check"
    ),
    ComparisonOutcome.UNRESOLVED: (
        "the selected check failed before and after the patch; the failure is "
        "unresolved or a different failure is present"
    ),
    ComparisonOutcome.POTENTIAL_REGRESSION: (
        "the selected check passed before the patch and failed after it; a "
        "potential regression is present"
    ),
    ComparisonOutcome.BASELINE_INCOMPLETE: (
        "the baseline check did not run, so post-patch results alone do not "
        "establish issue resolution"
    ),
    ComparisonOutcome.POST_PATCH_INCOMPLETE: (
        "the post-patch check did not run, so the comparison is incomplete and "
        "issue resolution is not established"
    ),
}

_COMPARISON_RESOLUTIONS: dict[ComparisonOutcome, str] = {
    ComparisonOutcome.CONSISTENT_IMPROVEMENT: (
        "Selected checks failed on the baseline commit and passed after the "
        "patch; this is consistent improvement, not final proof that the issue "
        "is resolved."
    ),
    ComparisonOutcome.NO_REGRESSION_DETECTED: (
        "Selected checks passed before and after the patch; no regression was "
        "detected in those checks, but issue resolution is not fully established."
    ),
    ComparisonOutcome.UNRESOLVED: (
        "Selected checks failed before and after the patch; the failure remains "
        "unresolved."
    ),
    ComparisonOutcome.POTENTIAL_REGRESSION: (
        "Selected checks passed before the patch and failed after it; a "
        "potential regression is present."
    ),
    ComparisonOutcome.BASELINE_INCOMPLETE: (
        "The baseline check did not run, so post-patch results alone do not "
        "establish issue resolution."
    ),
    ComparisonOutcome.POST_PATCH_INCOMPLETE: (
        "The post-patch check did not run; issue resolution is not established."
    ),
}


def classify_comparison_outcome(
    baseline: VerificationStatus, post_patch: VerificationStatus
) -> ComparisonOutcome:
    """Map two real outcomes onto the product's comparison table.

    ``NOT_RUN`` on either side takes precedence: an incomplete comparison is
    never reported as an improvement or a regression.
    """
    if baseline is VerificationStatus.NOT_RUN:
        return ComparisonOutcome.BASELINE_INCOMPLETE
    if post_patch is VerificationStatus.NOT_RUN:
        return ComparisonOutcome.POST_PATCH_INCOMPLETE
    if baseline is VerificationStatus.FAILED:
        if post_patch is VerificationStatus.PASSED:
            return ComparisonOutcome.CONSISTENT_IMPROVEMENT
        return ComparisonOutcome.UNRESOLVED
    if post_patch is VerificationStatus.FAILED:
        return ComparisonOutcome.POTENTIAL_REGRESSION
    return ComparisonOutcome.NO_REGRESSION_DETECTED


def comparison_interpretation(outcome: ComparisonOutcome) -> str:
    return _COMPARISON_INTERPRETATIONS[outcome]


def resolution_statement(
    outcome: ComparisonOutcome | None, overall: VerificationStatus
) -> str:
    """Evidence-honest wording for what the receipt actually establishes."""
    if outcome is None:
        if overall is VerificationStatus.PASSED:
            return "Selected checks passed; issue resolution not fully established."
        return "Verification did not complete; issue resolution is not established."

    statement = _COMPARISON_RESOLUTIONS[outcome]
    if overall is VerificationStatus.FAILED:
        statement += " One or more verification checks failed."
    return statement


class VerificationReceipt(BaseModel):
    checks: list[VerificationCheck]
    overall: VerificationStatus
    environment: str
    limitations: list[str] = []
    # The sandbox's network policy and what was actually proven about it.
    # ``egress_validation`` is PASSED only when the adversarial probe ran and
    # every egress attempt was refused.
    sandbox: SandboxPolicyRecord | None = None
    # Baseline/post provenance: the pinned commit, the exact patch bytes and
    # the deterministic comparison. Old persisted receipts deserialize with
    # these fields absent.
    base_commit: str | None = None
    patch_sha256: str | None = None
    comparison: VerificationComparison | None = None
    resolution_statement: str = ""
    created_at: datetime = Field(default_factory=utcnow)

    @model_validator(mode="after")
    def _comparison_matches_receipt(self) -> "VerificationReceipt":
        if self.comparison is not None:
            if self.base_commit is None:
                self.base_commit = self.comparison.base_commit
            elif self.base_commit != self.comparison.base_commit:
                raise ValueError("receipt base commit does not match the comparison")
            if self.patch_sha256 is None:
                self.patch_sha256 = self.comparison.patch_sha256
            elif self.patch_sha256 != self.comparison.patch_sha256:
                raise ValueError("receipt patch hash does not match the comparison")

        if not self.resolution_statement:
            self.resolution_statement = resolution_statement(
                self.comparison.outcome if self.comparison else None,
                self.overall,
            )
        return self
