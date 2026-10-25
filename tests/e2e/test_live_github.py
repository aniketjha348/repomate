"""Live end-to-end test against a real licensed public repository.

Opt-in only (network + clone):

    pytest -m network tests/e2e/test_live_github.py
"""

import pytest

from repomate_core.contracts import RepositoryInput, RunStatus, TaskSource
from repomate_core.orchestration.pipeline import PipelineConfig, run_pipeline

pytestmark = pytest.mark.network


def test_docs_task_on_public_repo(tmp_path):
    run_input = RepositoryInput(
        source=TaskSource.REPO_TASK,
        repo_url="https://github.com/psf/black",
        task="Add documentation for how to exclude directories from formatting to the README",
    )
    record = run_pipeline(
        run_input,
        config=PipelineConfig(runs_root=tmp_path / "runs"),
    )
    assert record.status is RunStatus.COMPLETED
    assert record.snapshot.license.status.value == "RECOGNIZED"
    assert record.snapshot.license.spdx_id  # clearly licensed target required
    assert record.artifact is not None and record.artifact.patch

    # Patch-level checks must pass. The repository test suite runs inside
    # the sandbox; black's suite needs its dependencies installed, so an
    # honest FAILED (exit != 0, import errors in the tail) is the expected
    # outcome in a bare environment — that is the product being honest,
    # not a bug.
    by_name = {c.name: c for c in record.receipt.checks}
    assert by_name["patch-path-policy"].status.value == "PASSED"
    assert by_name["patch-applies-on-pinned-commit"].status.value == "PASSED"
    suite = by_name["repository-test-suite"]
    assert suite.status.value == "FAILED"
    assert suite.exit_code not in (0, None)
    assert suite.command and "pytest" in suite.command
