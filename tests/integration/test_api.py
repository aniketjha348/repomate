"""Integration tests for the HTTP API (in-process execution)."""

from pathlib import Path

from fastapi.testclient import TestClient

from repomate_core.repository.workspace import RepoWorkspace


def _client(tmp_path: Path, local_repo: Path, monkeypatch):
    monkeypatch.setenv("REPOMATE_RUNS_ROOT", str(tmp_path / "runs"))
    monkeypatch.setenv("OLLAMA_API_KEY", "")   # heuristic planner, honestly labelled

    from repomate_core.orchestration import pipeline as pipeline_module
    from services.api import main as api_module

    monkeypatch.setattr(
        pipeline_module,
        "github_workspace_factory",
        lambda ref, dest, config: RepoWorkspace.from_local(local_repo),
    )
    return TestClient(api_module.app)


def test_health_reports_honest_planner(tmp_path, local_repo, monkeypatch):
    client = _client(tmp_path, local_repo, monkeypatch)
    response = client.get("/api/health")
    assert response.status_code == 200
    body = response.json()
    assert body["planner"] == "heuristic-v1"
    assert body["model_configured"] is False


def test_run_record_exposes_grounding_verdict(tmp_path, local_repo, monkeypatch):
    """The grounding verdict must reach the API surface, not stop at the
    pipeline: a client must be able to see which citations resolved."""
    client = _client(tmp_path, local_repo, monkeypatch)

    created = client.post(
        "/api/runs",
        json={
            "repo_url": "https://github.com/acme/fixture-project",
            "task": "Add documentation for the timeout option to the README quickstart",
        },
    )
    assert created.status_code == 202, created.text
    record = client.get(f"/api/runs/{created.json()['run_id']}").json()

    assert record["grounding"] is not None
    grounding = record["grounding"]
    assert grounding["claims"], "every plan must carry validated claims"
    assert grounding["unresolved_evidence_ids"] == []
    # The heuristic planner cites the evidence it actually retrieved.
    assert grounding["resolved_evidence_ids"]
    for claim in grounding["claims"]:
        assert claim["support_status"] in ("supported", "hypothesis")
        assert set(claim["matched_evidence_ids"]) <= set(grounding["resolved_evidence_ids"])


def test_create_and_fetch_run(tmp_path, local_repo, monkeypatch):
    client = _client(tmp_path, local_repo, monkeypatch)

    created = client.post(
        "/api/runs",
        json={
            "repo_url": "https://github.com/acme/fixture-project",
            "task": "Add documentation for the timeout option to the README quickstart",
        },
    )
    assert created.status_code == 202, created.text
    run_id = created.json()["run_id"]

    fetched = client.get(f"/api/runs/{run_id}")
    assert fetched.status_code == 200
    record = fetched.json()
    assert record["status"] in ("COMPLETED", "NEED_MORE_INFO")
    assert record["planner"] == "heuristic-v1"

    if record["status"] == "COMPLETED":
        patch = client.get(f"/api/runs/{run_id}/artifacts/patch")
        assert patch.status_code == 200
        assert "diff --git" in patch.text
        assert patch.headers["content-type"].startswith("text/x-diff")

    events = client.get(f"/api/runs/{run_id}/events")
    assert events.status_code == 200
    assert "event: done" in events.text


def test_invalid_url_is_a_controlled_400(tmp_path, local_repo, monkeypatch):
    client = _client(tmp_path, local_repo, monkeypatch)
    response = client.post(
        "/api/runs",
        json={"repo_url": "https://evil.example.com/a/b", "task": "document it"},
    )
    assert response.status_code == 400
    assert response.json()["detail"]["code"] == "INVALID_INPUT"


def test_incomplete_payload_is_422(tmp_path, local_repo, monkeypatch):
    client = _client(tmp_path, local_repo, monkeypatch)
    response = client.post("/api/runs", json={"repo_url": "https://github.com/a/b"})
    assert response.status_code == 422


def test_network_override_is_rejected(tmp_path, local_repo, monkeypatch):
    """A caller cannot ask the sandbox to enable networking."""
    client = _client(tmp_path, local_repo, monkeypatch)
    for field in (
        {"network": "host"},
        {"sandbox_network": "host"},
        {"egress": "allowed"},
    ):
        response = client.post(
            "/api/runs",
            json={
                "repo_url": "https://github.com/acme/fixture-project",
                "task": "Add documentation for the timeout option",
                **field,
            },
        )
        assert response.status_code == 422, (field, response.text)


def test_unknown_run_is_404(tmp_path, local_repo, monkeypatch):
    client = _client(tmp_path, local_repo, monkeypatch)
    assert client.get("/api/runs/run_missing").status_code == 404
