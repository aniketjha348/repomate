"""End-to-end bug-fix loop: model-proposed anchored edit repairs a real
failing test inside the verification sandbox.

The "model" here is a deterministic stand-in with the exact contract a
live model fulfils (task_type BUG_FIX + proposed_edits with verbatim
anchors) — the live gateway path is exercised by the network e2e and
scripts/model_matrix.py.
"""

from pathlib import Path

import pytest

from repomate_core.contracts import (
    ComparisonOutcome,
    ErrorCode,
    PlannedChange,
    ProposedEdit,
    RepositoryInput,
    RunStatus,
    TaskSource,
    VerificationStatus,
)
from repomate_core.orchestration.pipeline import run_pipeline
from repomate_core.orchestration.pipeline_config import PipelineConfig
from repomate_core.repository.workspace import RepoWorkspace
from repomate_core.verification.network_policy import EgressBackend, detect_egress_backend

requires_backend = pytest.mark.skipif(
    detect_egress_backend() is EgressBackend.NONE,
    reason="repository suites only execute when the egress-enforcing backend exists",
)

BROKEN_TEST = """from fixture.core import slugify

def test_slugify():
    assert slugify("Hello World") == "hello-world"
"""

FIXED_CORE = '''"""Core processing helpers."""


def slugify(text):
    """Convert text to a dashed slug (BUG: keeps spaces)."""
    return text.lower()


def process(items, timeout=30):
    """Process items with a request timeout (seconds)."""
    return [transform(item) for item in items]


def transform(item):
    return str(item).strip().lower()
'''


class ModelLikePlanner:
    """Emulates a model planner proposing an anchored bug fix."""

    name = "model:openai/gemma4:31b"

    def __init__(self, edits):
        self._edits = edits

    def plan(self, task_text, snapshot, evidence):
        from repomate_core.contracts import ContributionPlan, TaskType

        return ContributionPlan(
            task_type=TaskType.BUG_FIX,
            summary="Fix slugify to replace spaces with dashes",
            planned_changes=[
                PlannedChange(path="src/fixture/core.py", change_type="MODIFY", rationale="")
            ],
            evidence_ids=[e.id for e in evidence[:3]],
            proposed_edits=self._edits,
            planned_by=self.name,
        )


def _factory(local_repo: Path):
    return lambda ref, dest, config: RepoWorkspace.from_local(local_repo)


def _bug_input() -> RepositoryInput:
    return RepositoryInput(
        source=TaskSource.REPO_TASK,
        repo_url="https://github.com/acme/fixture-project",
        task="fix the bug where slugify keeps spaces instead of dashing them",
    )


@pytest.fixture
def buggy_repo(local_repo: Path) -> Path:
    (local_repo / "src" / "fixture" / "core.py").write_text(
        FIXED_CORE, encoding="utf-8", newline="\n"
    )
    (local_repo / "tests" / "test_core.py").write_text(
        BROKEN_TEST, encoding="utf-8", newline="\n"
    )
    ws = RepoWorkspace.from_local(local_repo)
    ws.git("add", "-A")
    ws.git("-c", "user.name=T", "-c", "user.email=t@t.invalid",
           "commit", "-m", "introduce slugify bug with failing test")
    return local_repo


@requires_backend
def test_bugfix_loop_fixes_suite(buggy_repo, tmp_path):
    planner = ModelLikePlanner([
        ProposedEdit(
            path="src/fixture/core.py",
            old_text='    """Convert text to a dashed slug (BUG: keeps spaces)."""\n    return text.lower()',
            new_text='    """Convert text to a dashed slug."""\n    return text.lower().replace(" ", "-")',
            rationale="replace spaces with dashes",
        )
    ])
    record = run_pipeline(
        _bug_input(),
        config=PipelineConfig(runs_root=tmp_path / "runs", planner=planner),
        workspace_factory=_factory(buggy_repo),
    )

    assert record.status is RunStatus.COMPLETED
    assert record.artifact is not None
    assert record.artifact.kind.value == "PATCH_DIFF"
    assert "replace" in record.artifact.patch

    by_name = {c.name: c for c in record.receipt.checks}
    assert by_name["patch-applies-on-pinned-commit"].status.value == "PASSED"
    # The bug's failing test now passes inside the sandbox.
    suite = by_name["repository-test-suite"]
    assert suite.status.value == "PASSED", suite.output_tail
    assert suite.exit_code == 0

    # The same suite failed on the clean baseline commit, in a separate
    # workspace. This is consistent improvement, not a "verified fix".
    comparison = record.receipt.comparison
    assert comparison is not None
    assert comparison.outcome is ComparisonOutcome.CONSISTENT_IMPROVEMENT
    assert comparison.baseline.status is VerificationStatus.FAILED
    assert comparison.post_patch.status is VerificationStatus.PASSED
    assert comparison.commands_match is True
    assert record.receipt.base_commit == record.snapshot.commit_sha
    assert "not final proof" in record.receipt.resolution_statement.lower()


def test_unanchored_model_edit_is_typed_model_error(buggy_repo, tmp_path):
    planner = ModelLikePlanner([
        ProposedEdit(
            path="src/fixture/core.py",
            old_text="this text is not in the file at all",
            new_text="whatever",
        )
    ])
    record = run_pipeline(
        _bug_input(),
        config=PipelineConfig(runs_root=tmp_path / "runs", planner=planner),
        workspace_factory=_factory(buggy_repo),
    )
    assert record.status is RunStatus.FAILED
    assert record.error.code is ErrorCode.MODEL
    assert "anchor" in record.error.detail.lower()


def test_docs_task_uses_model_content_draft(local_repo, docs_task_input, tmp_path):
    from repomate_core.contracts import ContributionPlan, TaskType

    class DraftPlanner:
        name = "model:openai/gemma4:31b"

        def plan(self, task_text, snapshot, evidence):
            return ContributionPlan(
                task_type=TaskType.DOCUMENTATION,
                summary="document the timeout option",
                planned_changes=[
                    PlannedChange(path="README.md", change_type="MODIFY", rationale="")
                ],
                evidence_ids=[e.id for e in evidence[:3]],
                content_draft=(
                    "Set `FIXTURE_TIMEOUT` to control request timeouts.\n\n"
                    "Defaults to 30 seconds; retries honour `FIXTURE_RETRIES`."
                ),
                planned_by=self.name,
            )

    record = run_pipeline(
        docs_task_input,
        config=PipelineConfig(runs_root=tmp_path / "runs", planner=DraftPlanner()),
        workspace_factory=_factory(local_repo),
    )
    assert record.status is RunStatus.COMPLETED
    patch = record.artifact.patch
    assert "FIXTURE_TIMEOUT" in patch
    # Model-written body, not the heuristic template.
    assert "This section addresses the following contribution task" not in patch
    assert record.artifact.generated_by.startswith("model:openai/")
