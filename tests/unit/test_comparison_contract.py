"""Contracts for deterministic baseline vs post-patch verification."""

import pytest
from pydantic import ValidationError

from repomate_core.contracts import (
    ComparisonOutcome,
    SandboxPolicyRecord,
    VerificationComparison,
    VerificationReceipt,
    VerificationRunRecord,
    VerificationStatus,
    classify_comparison_outcome,
    comparison_interpretation,
    resolution_statement,
)

BASE = "a" * 40
OTHER = "b" * 40
PATCH_SHA = "c" * 64
COMMAND = "python -m pytest -q"


def _run(
    phase: str,
    status: VerificationStatus,
    *,
    command: str | None = COMMAND,
    commit: str = BASE,
    reason: str = "",
) -> VerificationRunRecord:
    return VerificationRunRecord(
        phase=phase,  # type: ignore[arg-type]
        commit_sha=commit,
        command=command,
        status=status,
        exit_code=(
            None
            if status is VerificationStatus.NOT_RUN
            else (0 if status is VerificationStatus.PASSED else 1)
        ),
        duration_ms=None if command is None else 12,
        output_summary="captured output",
        reason=reason
        or ("did not run: fixture reason" if status is VerificationStatus.NOT_RUN else ""),
    )


def _comparison(
    baseline: VerificationStatus, post: VerificationStatus
) -> VerificationComparison:
    outcome = classify_comparison_outcome(baseline, post)
    return VerificationComparison(
        base_commit=BASE,
        patch_sha256=PATCH_SHA,
        baseline=_run("baseline", baseline),
        post_patch=_run("post_patch", post),
        outcome=outcome,
        interpretation=comparison_interpretation(outcome),
    )


@pytest.mark.parametrize(
    ("baseline", "post", "expected"),
    [
        (VerificationStatus.FAILED, VerificationStatus.PASSED, ComparisonOutcome.CONSISTENT_IMPROVEMENT),
        (VerificationStatus.PASSED, VerificationStatus.PASSED, ComparisonOutcome.NO_REGRESSION_DETECTED),
        (VerificationStatus.FAILED, VerificationStatus.FAILED, ComparisonOutcome.UNRESOLVED),
        (VerificationStatus.PASSED, VerificationStatus.FAILED, ComparisonOutcome.POTENTIAL_REGRESSION),
        (VerificationStatus.NOT_RUN, VerificationStatus.PASSED, ComparisonOutcome.BASELINE_INCOMPLETE),
        (VerificationStatus.NOT_RUN, VerificationStatus.NOT_RUN, ComparisonOutcome.BASELINE_INCOMPLETE),
        (VerificationStatus.PASSED, VerificationStatus.NOT_RUN, ComparisonOutcome.POST_PATCH_INCOMPLETE),
        (VerificationStatus.FAILED, VerificationStatus.NOT_RUN, ComparisonOutcome.POST_PATCH_INCOMPLETE),
    ],
)
def test_classification_table(baseline, post, expected):
    assert classify_comparison_outcome(baseline, post) is expected
    assert _comparison(baseline, post).outcome is expected


def test_baseline_not_run_takes_precedence():
    # The product table says NOT_RUN -> Any = baseline incomplete, including
    # the case where post-patch also did not run.
    assert (
        classify_comparison_outcome(
            VerificationStatus.NOT_RUN, VerificationStatus.NOT_RUN
        )
        is ComparisonOutcome.BASELINE_INCOMPLETE
    )


def test_executed_comparison_requires_one_exact_command():
    baseline = _run("baseline", VerificationStatus.PASSED)
    post = _run("post_patch", VerificationStatus.PASSED, command="make test")
    with pytest.raises(ValidationError, match="same exact command"):
        VerificationComparison(
            base_commit=BASE,
            patch_sha256=PATCH_SHA,
            baseline=baseline,
            post_patch=post,
            outcome=ComparisonOutcome.NO_REGRESSION_DETECTED,
            interpretation=comparison_interpretation(
                ComparisonOutcome.NO_REGRESSION_DETECTED
            ),
        )


def test_commands_match_reports_incomplete_pairing():
    baseline = _run("baseline", VerificationStatus.PASSED)
    post = _run("post_patch", VerificationStatus.NOT_RUN, command=None)
    comparison = VerificationComparison(
        base_commit=BASE,
        patch_sha256=PATCH_SHA,
        baseline=baseline,
        post_patch=post,
        outcome=ComparisonOutcome.POST_PATCH_INCOMPLETE,
        interpretation=comparison_interpretation(
            ComparisonOutcome.POST_PATCH_INCOMPLETE
        ),
    )
    assert comparison.commands_match is False


def test_commands_match_is_none_when_no_command_was_selected():
    baseline = _run("baseline", VerificationStatus.NOT_RUN, command=None)
    post = _run("post_patch", VerificationStatus.NOT_RUN, command=None)
    comparison = VerificationComparison(
        base_commit=BASE,
        patch_sha256=PATCH_SHA,
        baseline=baseline,
        post_patch=post,
        outcome=ComparisonOutcome.BASELINE_INCOMPLETE,
        interpretation=comparison_interpretation(
            ComparisonOutcome.BASELINE_INCOMPLETE
        ),
    )
    assert comparison.commands_match is None


def test_not_run_comparison_requires_a_reason():
    with pytest.raises(ValidationError, match="explicit reason"):
        VerificationRunRecord(
            phase="post_patch",
            commit_sha=BASE,
            status=VerificationStatus.NOT_RUN,
        )


def test_outcome_cannot_contradict_the_recorded_statuses():
    with pytest.raises(ValidationError, match="does not match the run statuses"):
        VerificationComparison(
            base_commit=BASE,
            patch_sha256=PATCH_SHA,
            baseline=_run("baseline", VerificationStatus.PASSED),
            post_patch=_run("post_patch", VerificationStatus.PASSED),
            outcome=ComparisonOutcome.POTENTIAL_REGRESSION,
            interpretation=comparison_interpretation(
                ComparisonOutcome.POTENTIAL_REGRESSION
            ),
        )


def test_post_patch_only_results_do_not_claim_resolution():
    statement = resolution_statement(
        ComparisonOutcome.BASELINE_INCOMPLETE, VerificationStatus.PASSED
    )
    assert "issue resolution" in statement
    assert "post-patch results alone" in statement
    assert "resolved" not in statement.lower().replace("resolution", "")


def test_no_comparison_uses_evidence_honest_default():
    statement = resolution_statement(None, VerificationStatus.PASSED)
    assert statement == "Selected checks passed; issue resolution not fully established."


def test_failed_overall_is_appended_to_resolution():
    statement = resolution_statement(
        ComparisonOutcome.NO_REGRESSION_DETECTED, VerificationStatus.FAILED
    )
    assert "One or more verification checks failed." in statement


def test_receipt_derives_provenance_and_statement_from_comparison():
    comparison = _comparison(VerificationStatus.FAILED, VerificationStatus.PASSED)
    receipt = VerificationReceipt(
        checks=[],
        overall=VerificationStatus.PASSED,
        environment="test",
        comparison=comparison,
    )
    assert receipt.base_commit == BASE
    assert receipt.patch_sha256 == PATCH_SHA
    assert "consistent improvement" in receipt.resolution_statement.lower()
    assert "not final proof" in receipt.resolution_statement.lower()


def test_receipt_rejects_conflicting_provenance():
    comparison = _comparison(VerificationStatus.PASSED, VerificationStatus.PASSED)
    with pytest.raises(ValidationError, match="base commit"):
        VerificationReceipt(
            checks=[],
            overall=VerificationStatus.PASSED,
            environment="test",
            base_commit=OTHER,
            comparison=comparison,
        )


def test_legacy_receipt_without_comparison_still_serializes():
    receipt = VerificationReceipt(
        checks=[], overall=VerificationStatus.PASSED, environment="test"
    )
    restored = VerificationReceipt.model_validate_json(receipt.model_dump_json())
    assert restored.comparison is None
    assert restored.resolution_statement.startswith("Selected checks passed")


def test_sandbox_policy_record_is_unchanged():
    record = SandboxPolicyRecord(
        network_mode="disabled",
        backend="bwrap",
        policy_enforced=True,
        egress_validation="PASSED",
        egress_detail="blocked",
    )
    assert record.egress_validation == "PASSED"
