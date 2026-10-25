"""Unit tests for the Phase 1 contracts."""

import pytest
from pydantic import ValidationError

from repomate_core.contracts import (
    ArtifactKind,
    ContributionArtifact,
    RepositoryInput,
    RunRecord,
    TaskSource,
    VerificationCheck,
    VerificationStatus,
)


class TestRepositoryInput:
    def test_issue_mode_requires_issue_url(self):
        with pytest.raises(ValidationError):
            RepositoryInput(source=TaskSource.GITHUB_ISSUE)

    def test_repo_mode_requires_repo_and_task(self):
        with pytest.raises(ValidationError):
            RepositoryInput(source=TaskSource.REPO_TASK, repo_url="https://github.com/a/b")

    def test_repo_mode_rejects_blank_task(self):
        with pytest.raises(ValidationError):
            RepositoryInput(
                source=TaskSource.REPO_TASK,
                repo_url="https://github.com/a/b",
                task="   ",
            )


class TestVerificationCheck:
    def test_not_run_requires_reason(self):
        with pytest.raises(ValidationError):
            VerificationCheck(name="suite", status=VerificationStatus.NOT_RUN)

    def test_not_run_with_reason_ok(self):
        check = VerificationCheck(name="suite", status=VerificationStatus.NOT_RUN, reason="sandbox pending")
        assert check.reason == "sandbox pending"


class TestRunRecordRoundTrip:
    def test_serialize_deserialize(self):
        record = RunRecord(
            run_id="run_test",
            input=RepositoryInput(
                source=TaskSource.REPO_TASK,
                repo_url="https://github.com/a/b",
                task="document the thing",
            ),
            artifact=ContributionArtifact(
                kind=ArtifactKind.DOCS_DIFF,
                patch="+++ b/README.md\n",
                affected_paths=["README.md"],
                based_on_commit="abc123",
                generated_by="heuristic-v1",
            ),
        )
        restored = RunRecord.model_validate_json(record.model_dump_json())
        assert restored.artifact.affected_paths == ["README.md"]
        assert restored.is_terminal is False
