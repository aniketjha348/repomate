"""Phase 5 integration: Celery task execution (eager), SQLite-backed API,
and the metrics endpoint."""

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from repomate_core.contracts import RepositoryInput, RunStatus, TaskSource
from repomate_core.orchestration.pipeline_config import PipelineConfig
from repomate_core.orchestration.store_factory import build_store
from repomate_core.repository.workspace import RepoWorkspace


def _local_factory(local_repo: Path):
    def factory(ref, dest, config):
        return RepoWorkspace.from_local(local_repo)
    return factory


@pytest.fixture
def eager_celery(monkeypatch, tmp_path):
    monkeypatch.setenv("REDIS_URL", "memory://")
    monkeypatch.setenv("CELERY_TASK_ALWAYS_EAGER", "1")
    monkeypatch.setenv("REPOMATE_DATABASE_URL", f"sqlite:///{tmp_path}/runs.db")
    import importlib

    import services.worker.celery_app as celery_module
    import services.worker.tasks as tasks_module

    importlib.reload(celery_module)
    importlib.reload(tasks_module)
    return tasks_module


def test_worker_app_includes_task_module():
    # Without this, a real worker starts but discards every delivery with
    # "Received unregistered task of type 'repomate.execute_run'".
    from services.worker.celery_app import app

    assert "services.worker.tasks" in (app.conf.include or ())


def test_worker_app_enforces_run_time_limits_and_concurrency(monkeypatch):
    monkeypatch.setenv("REPOMATE_MAX_RUN_SECONDS", "120")
    monkeypatch.setenv("REPOMATE_WORKER_CONCURRENCY", "4")
    import importlib

    import services.worker.celery_app as celery_module

    importlib.reload(celery_module)
    try:
        # The soft limit finalises the run honestly; the hard limit is a
        # backstop for a genuinely wedged child.
        assert celery_module.app.conf.task_soft_time_limit == 120.0
        assert celery_module.app.conf.task_time_limit == 150.0
        assert celery_module.app.conf.worker_concurrency == 4
    finally:
        monkeypatch.undo()
        importlib.reload(celery_module)


def test_celery_task_executes_pipeline(tmp_path, local_repo, eager_celery, monkeypatch):
    from repomate_core.orchestration import pipeline as pipeline_module

    monkeypatch.setattr(pipeline_module, "github_workspace_factory", _local_factory(local_repo))

    run_input = RepositoryInput(
        source=TaskSource.REPO_TASK,
        repo_url="https://github.com/acme/fixture-project",
        task="Add documentation for the timeout option to the README",
    )
    config = PipelineConfig(
        runs_root=tmp_path / "runs",
        database_url=f"sqlite:///{tmp_path}/runs.db",
    )
    from services.api.dispatch import _config_dict

    result = eager_celery.execute_run.apply(
        args=["run_celery_1", run_input.model_dump(mode="json"), _config_dict(config)]
    ).get()

    assert result == "COMPLETED"
    store = build_store(config.runs_root, config.database_url)
    record = store.load_run("run_celery_1")
    assert record.status is RunStatus.COMPLETED
    assert store.load_events("run_celery_1")  # events persisted durably


def test_api_with_sqlite_store_and_metrics(tmp_path, local_repo, monkeypatch):
    monkeypatch.setenv("REPOMATE_RUNS_ROOT", str(tmp_path / "runs"))
    monkeypatch.setenv("REPOMATE_DATABASE_URL", f"sqlite:///{tmp_path}/api.db")
    monkeypatch.setenv("OLLAMA_API_KEY", "")

    from repomate_core.orchestration import pipeline as pipeline_module
    from services.api import main as api_module

    monkeypatch.setattr(
        pipeline_module, "github_workspace_factory", _local_factory(local_repo)
    )
    client = TestClient(api_module.app)

    created = client.post(
        "/api/runs",
        json={
            "repo_url": "https://github.com/acme/fixture-project",
            "task": "Add documentation for the timeout option to the README",
        },
    )
    assert created.status_code == 202, created.text
    run_id = created.json()["run_id"]

    fetched = client.get(f"/api/runs/{run_id}")
    assert fetched.status_code == 200
    assert fetched.json()["status"] == "COMPLETED"

    # Artifact served from the SQL store, not the filesystem.
    patch = client.get(f"/api/runs/{run_id}/artifacts/patch")
    assert patch.status_code == 200
    assert "diff --git" in patch.text

    metrics = client.get("/api/metrics").json()
    assert metrics["runs_by_status"].get("COMPLETED") == 1
    assert metrics["runs_by_planner"].get("heuristic-v1") == 1
    assert metrics["execution"] == "inproc"
    assert metrics["sandbox_enabled"] is True
    # The endpoint is unauthenticated in the default deployment; it must not
    # leak filesystem paths or environment-file details.
    assert "env_file" not in metrics
    assert not any(
        isinstance(value, str) and ("/" in value or "\\" in value)
        for value in metrics.values()
    )


def test_api_dispatches_to_celery_when_configured(tmp_path, local_repo, monkeypatch):
    monkeypatch.setenv("REPOMATE_RUNS_ROOT", str(tmp_path / "runs"))
    monkeypatch.setenv("REPOMATE_DATABASE_URL", f"sqlite:///{tmp_path}/api2.db")
    monkeypatch.setenv("REPOMATE_EXECUTION", "celery")
    monkeypatch.setenv("REDIS_URL", "memory://")
    monkeypatch.setenv("CELERY_TASK_ALWAYS_EAGER", "1")

    from repomate_core.orchestration import pipeline as pipeline_module
    from services.api import main as api_module

    monkeypatch.setattr(
        pipeline_module, "github_workspace_factory", _local_factory(local_repo)
    )
    client = TestClient(api_module.app)

    created = client.post(
        "/api/runs",
        json={
            "repo_url": "https://github.com/acme/fixture-project",
            "task": "Add documentation for the retry option to the README",
        },
    )
    assert created.status_code == 202
    run_id = created.json()["run_id"]

    # Eager mode executes inline, so the record is already terminal and
    # /api/metrics reports the celery execution mode.
    fetched = client.get(f"/api/runs/{run_id}").json()
    assert fetched["status"] == "COMPLETED"
    assert client.get("/api/metrics").json()["execution"] == "celery"
