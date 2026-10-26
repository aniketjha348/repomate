"""Real baseline vs post-patch verification in separate sandboxed checkouts."""

import hashlib
from pathlib import Path

import pytest

from repomate_core.artifacts.patch import CODE_FIX_PATCH_POLICY
from repomate_core.contracts import (
    ArtifactKind,
    ComparisonOutcome,
    ContributionArtifact,
    VerificationStatus,
)
from repomate_core.repository.workspace import RepoWorkspace
from repomate_core.verification.network_policy import EgressBackend, detect_egress_backend
from repomate_core.verification.runner import run_verification
from repomate_core.verification.sandbox import SandboxLimits

requires_backend = pytest.mark.skipif(
    detect_egress_backend() is EgressBackend.NONE,
    reason="repository suites only execute when the egress-enforcing backend exists",
)

PYPROJECT = (
    "[project]\nname='t'\nversion='0.1.0'\n\n"
    "[tool.pytest.ini_options]\npythonpath=['src']\n"
)

BROKEN_CORE = '''def add(a, b):
    return a - b
'''

FIXED_CORE = '''def add(a, b):
    return a + b
'''

FIXED_WITH_NOTE = '''"""Core helpers."""


def add(a, b):
    return a + b
'''

BROKEN_WITH_NOTE = '''"""Core helpers."""


def add(a, b):
    return a - b
'''

PASSING_TEST = "from t.core import add\n\n\ndef test_add():\n    assert add(1, 2) == 3\n"


def _repo_with(local_repo: Path, core: str) -> RepoWorkspace:
    (local_repo / "tests" / "test_core.py").unlink(missing_ok=True)
    (local_repo / "pyproject.toml").write_text(PYPROJECT, encoding="utf-8", newline="\n")
    (local_repo / "src" / "t").mkdir(parents=True, exist_ok=True)
    (local_repo / "src" / "t" / "__init__.py").write_text("", encoding="utf-8")
    (local_repo / "src" / "t" / "core.py").write_text(core, encoding="utf-8", newline="\n")
    (local_repo / "tests" / "test_add.py").write_text(
        PASSING_TEST, encoding="utf-8", newline="\n"
    )
    ws = RepoWorkspace.from_local(local_repo)
    ws.git("add", "-A")
    ws.git(
        "-c", "user.name=T", "-c", "user.email=t@t.invalid",
        "commit", "-m", "comparison fixture",
    )
    return ws


def _artifact_for(ws: RepoWorkspace, new_core: str) -> ContributionArtifact:
    ws.write_text("src/t/core.py", new_core)
    patch = ws.diff()
    ws.reset_hard()
    assert patch.strip(), "fixture patch must not be empty"
    return ContributionArtifact(
        kind=ArtifactKind.PATCH_DIFF,
        patch=patch,
        affected_paths=["src/t/core.py"],
        based_on_commit=ws.commit_sha,
        generated_by="test",
    )


def _verify(ws: RepoWorkspace, artifact: ContributionArtifact, **kwargs):
    return run_verification(
        ws,
        artifact,
        CODE_FIX_PATCH_POLICY,
        limits=SandboxLimits(wall_time_seconds=90),
        **kwargs,
    )


@requires_backend
def test_failed_to_passed_is_consistent_improvement(local_repo, tmp_path):
    ws = _repo_with(local_repo, BROKEN_CORE)
    artifact = _artifact_for(ws, FIXED_CORE)

    receipt = _verify(ws, artifact)

    comparison = receipt.comparison
    assert comparison is not None
    assert comparison.outcome is ComparisonOutcome.CONSISTENT_IMPROVEMENT
    assert comparison.baseline.status is VerificationStatus.FAILED
    assert comparison.post_patch.status is VerificationStatus.PASSED
    assert comparison.baseline.exit_code not in (0, None)
    assert comparison.post_patch.exit_code == 0
    assert comparison.commands_match is True
    assert comparison.baseline.command == comparison.post_patch.command
    assert comparison.baseline.duration_ms is not None
    assert comparison.post_patch.duration_ms is not None
    assert comparison.baseline.output_summary
    assert comparison.post_patch.output_summary

    assert receipt.base_commit == ws.commit_sha
    assert receipt.patch_sha256 == hashlib.sha256(artifact.patch.encode("utf-8")).hexdigest()
    assert "consistent improvement" in receipt.resolution_statement.lower()
    assert "not final proof" in receipt.resolution_statement.lower()

    # The run workspace is never patched in place: both checks used clones.
    assert "a - b" in (local_repo / "src" / "t" / "core.py").read_text(encoding="utf-8")


@requires_backend
def test_passed_to_failed_is_potential_regression(local_repo, tmp_path):
    ws = _repo_with(local_repo, FIXED_CORE)
    artifact = _artifact_for(ws, BROKEN_CORE)

    receipt = _verify(ws, artifact)

    comparison = receipt.comparison
    assert comparison is not None
    assert comparison.outcome is ComparisonOutcome.POTENTIAL_REGRESSION
    assert comparison.baseline.status is VerificationStatus.PASSED
    assert comparison.post_patch.status is VerificationStatus.FAILED
    assert "potential regression" in receipt.resolution_statement.lower()


@requires_backend
def test_passed_to_passed_is_no_regression_detected(local_repo, tmp_path):
    ws = _repo_with(local_repo, FIXED_CORE)
    artifact = _artifact_for(ws, FIXED_WITH_NOTE)

    receipt = _verify(ws, artifact)

    comparison = receipt.comparison
    assert comparison is not None
    assert comparison.outcome is ComparisonOutcome.NO_REGRESSION_DETECTED
    assert comparison.baseline.status is VerificationStatus.PASSED
    assert comparison.post_patch.status is VerificationStatus.PASSED
    assert "issue resolution is not fully established" in receipt.resolution_statement


@requires_backend
def test_failed_to_failed_is_unresolved(local_repo, tmp_path):
    ws = _repo_with(local_repo, BROKEN_CORE)
    artifact = _artifact_for(ws, BROKEN_WITH_NOTE)

    receipt = _verify(ws, artifact)

    comparison = receipt.comparison
    assert comparison is not None
    assert comparison.outcome is ComparisonOutcome.UNRESOLVED
    assert comparison.baseline.status is VerificationStatus.FAILED
    assert comparison.post_patch.status is VerificationStatus.FAILED
    assert "unresolved" in receipt.resolution_statement.lower()


def test_disabled_sandbox_reports_baseline_incomplete(local_repo):
    ws = _repo_with(local_repo, FIXED_CORE)
    artifact = _artifact_for(ws, FIXED_WITH_NOTE)

    receipt = _verify(ws, artifact, sandbox_enabled=False)

    comparison = receipt.comparison
    assert comparison is not None
    assert comparison.outcome is ComparisonOutcome.BASELINE_INCOMPLETE
    assert comparison.baseline.status is VerificationStatus.NOT_RUN
    assert comparison.post_patch.status is VerificationStatus.NOT_RUN
    assert "disabled" in comparison.baseline.reason
    assert "post-patch results alone do not establish issue resolution" in (
        receipt.resolution_statement
    )
    # A post-patch-only outcome is never promoted to a verified fix.
    assert "verified fix" not in receipt.resolution_statement.lower()


def test_patch_apply_failure_leaves_post_patch_incomplete(local_repo):
    ws = _repo_with(local_repo, FIXED_CORE)
    artifact = ContributionArtifact(
        kind=ArtifactKind.PATCH_DIFF,
        patch="+++ b/src/t/core.py\n@@ -1 +1,2 @@\n+not a real patch\n",
        affected_paths=["src/t/core.py"],
        based_on_commit=ws.commit_sha,
        generated_by="test",
    )

    receipt = _verify(ws, artifact)

    by_name = {check.name: check for check in receipt.checks}
    assert by_name["patch-applies-on-pinned-commit"].status is VerificationStatus.FAILED
    comparison = receipt.comparison
    assert comparison is not None
    assert comparison.post_patch.status is VerificationStatus.NOT_RUN
    assert "did not apply" in comparison.post_patch.reason
    # On hosts without an egress backend the baseline is also unavailable, so
    # baseline-incomplete takes precedence; with a backend it is post-patch
    # incomplete. Both are honest: neither claims a result.
    expected = (
        ComparisonOutcome.POST_PATCH_INCOMPLETE
        if detect_egress_backend() is not EgressBackend.NONE
        else ComparisonOutcome.BASELINE_INCOMPLETE
    )
    assert comparison.outcome is expected
