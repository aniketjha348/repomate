"""Fair-use admission over HTTP: typed 429s, concurrency cap, metrics."""

from pathlib import Path

from fastapi.testclient import TestClient

from repomate_core.contracts import RepositoryInput, RunRecord, RunStatus, TaskSource
from repomate_core.orchestration.store import RunStore
from repomate_core.repository.workspace import RepoWorkspace

_VALID_RUN = {
    "repo_url": "https://github.com/acme/fixture-project",
    "task": "Add documentation for the timeout option to the README quickstart",
}


def _client(tmp_path: Path, local_repo: Path, monkeypatch, **env: object) -> TestClient:
    monkeypatch.setenv("REPOMATE_RUNS_ROOT", str(tmp_path / "runs"))
    monkeypatch.setenv("OLLAMA_API_KEY", "")
    for key, value in env.items():
        monkeypatch.setenv(key, str(value))

    from repomate_core.orchestration import pipeline as pipeline_module
    from services.api import main as api_module

    monkeypatch.setattr(
        pipeline_module,
        "github_workspace_factory",
        lambda ref, dest, config: RepoWorkspace.from_local(local_repo),
    )
    return TestClient(api_module.app)


def _active_record() -> RunRecord:
    return RunRecord(
        run_id="run_active",
        input=RepositoryInput(
            source=TaskSource.REPO_TASK,
            repo_url="https://github.com/acme/fixture-project",
            task="stay active",
        ),
        status=RunStatus.RUNNING,
    )


def test_rate_limit_returns_typed_429_with_retry_after(
    tmp_path, local_repo, monkeypatch
):
    client = _client(
        tmp_path,
        local_repo,
        monkeypatch,
        REPOMATE_RATE_LIMIT_REQUESTS=2,
        REPOMATE_RATE_LIMIT_WINDOW_SECONDS=60,
        REPOMATE_MAX_CONCURRENT_RUNS=10,
    )

    for _ in range(2):
        created = client.post("/api/runs", json=_VALID_RUN)
        assert created.status_code == 202, created.text

    rejected = client.post("/api/runs", json=_VALID_RUN)
    assert rejected.status_code == 429
    assert rejected.json()["detail"]["code"] == "RATE_LIMITED"
    assert int(rejected.headers["retry-after"]) >= 1

    # A rejected submission never creates a run record.
    store = RunStore(tmp_path / "runs")
    assert len(store.list_run_ids()) == 2


def test_forwarded_header_cannot_bypass_the_limit(tmp_path, local_repo, monkeypatch):
    client = _client(
        tmp_path,
        local_repo,
        monkeypatch,
        REPOMATE_RATE_LIMIT_REQUESTS=1,
        REPOMATE_MAX_CONCURRENT_RUNS=10,
    )
    first = client.post("/api/runs", json=_VALID_RUN)
    assert first.status_code == 202, first.text

    second = client.post(
        "/api/runs",
        json=_VALID_RUN,
        headers={"X-Forwarded-For": "203.0.113.9"},
    )
    assert second.status_code == 429, "no trusted proxy is configured"


def test_concurrent_run_cap_rejects_new_work(tmp_path, local_repo, monkeypatch):
    client = _client(
        tmp_path,
        local_repo,
        monkeypatch,
        REPOMATE_MAX_CONCURRENT_RUNS=1,
    )
    store = RunStore(tmp_path / "runs")
    store.save_run(_active_record())

    response = client.post("/api/runs", json=_VALID_RUN)
    assert response.status_code == 429
    detail = response.json()["detail"]
    assert detail["code"] == "RATE_LIMITED"
    assert "concurrent-run limit" in detail["message"]

    metrics = client.get("/api/metrics").json()
    assert metrics["fair_use"]["active_runs"] == 1
    assert metrics["fair_use"]["max_concurrent_runs"] == 1
    assert metrics["fair_use"]["concurrency_limited"] == 1


def test_metrics_expose_admission_state(tmp_path, local_repo, monkeypatch):
    client = _client(
        tmp_path,
        local_repo,
        monkeypatch,
        REPOMATE_RATE_LIMIT_REQUESTS=5,
        REPOMATE_RATE_LIMIT_WINDOW_SECONDS=30,
        REPOMATE_MAX_CONCURRENT_RUNS=2,
    )
    body = client.get("/api/metrics").json()["fair_use"]
    assert body["max_concurrent_runs"] == 2
    assert body["rate_limit_requests"] == 5
    assert body["rate_limit_window_seconds"] == 30
    assert body["active_runs"] == 0
