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
    assert record.receipt.overall.value == "PASSED"
