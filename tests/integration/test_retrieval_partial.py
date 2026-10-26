"""A retrieval budget hit ends the run as PARTIAL, never as COMPLETED."""

from pathlib import Path

from repomate_core.contracts import (
    RetrievalLimit,
    RetrievalLimits,
    RetrievalStatus,
    RepositoryInput,
    RunStatus,
    TaskSource,
)
from repomate_core.orchestration.pipeline import run_pipeline
from repomate_core.orchestration.pipeline_config import PipelineConfig
from repomate_core.orchestration.store import RunStore
from repomate_core.repository.workspace import RepoWorkspace


def _factory(local_repo: Path):
    def factory(ref, dest, config):
        return RepoWorkspace.from_local(local_repo)

    return factory


def _config(tmp_path: Path, limits: RetrievalLimits) -> PipelineConfig:
    return PipelineConfig(
        runs_root=tmp_path / "runs",
        keep_workspace=False,
        retrieval_limits=limits,
    )


def test_retrieval_limit_returns_partial_without_artifact(tmp_path, local_repo):
    run_input = RepositoryInput(
        source=TaskSource.REPO_TASK,
        repo_url="https://github.com/acme/fixture-project",
        task="Add documentation for the timeout option to the README quickstart",
    )

    record = run_pipeline(
        run_input,
        config=_config(tmp_path, RetrievalLimits(max_files=1)),
        workspace_factory=_factory(local_repo),
    )

    assert record.status is RunStatus.PARTIAL
    assert record.is_terminal
    assert record.artifact is None
    assert record.receipt is None
    assert record.plan is None
    assert record.error is None
    assert record.retrieval is not None
    assert record.retrieval.status is RetrievalStatus.PARTIAL
    hits = {hit.limit for hit in record.retrieval.limit_hits}
    assert RetrievalLimit.MAX_FILES in hits
    assert "PARTIAL" in record.retrieval.summary
    assert "not examined" in record.retrieval.summary

    persisted = RunStore(tmp_path / "runs").load_run(record.run_id)
    assert persisted is not None
    assert persisted.status is RunStatus.PARTIAL
    assert persisted.retrieval is not None
    assert persisted.retrieval.status is RetrievalStatus.PARTIAL


def test_complete_retrieval_still_completes_the_run(tmp_path, local_repo):
    run_input = RepositoryInput(
        source=TaskSource.REPO_TASK,
        repo_url="https://github.com/acme/fixture-project",
        task="Add documentation for the timeout option to the README quickstart",
    )

    record = run_pipeline(
        run_input,
        config=_config(tmp_path, RetrievalLimits()),
        workspace_factory=_factory(local_repo),
    )

    assert record.status is RunStatus.COMPLETED
    assert record.retrieval is not None
    assert record.retrieval.status is RetrievalStatus.COMPLETE
    assert record.retrieval.limit_hits == []
