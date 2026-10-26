"""API startup maintenance: stale workspace sweep must not crash startup."""

from __future__ import annotations

import os
import time
from pathlib import Path

from fastapi import FastAPI

from repomate_core.contracts import RepositoryInput, RunRecord, TaskSource
from repomate_core.orchestration.store import RunStore
from services.api.app import _sweep_stale_workspaces


def test_sweep_sets_app_state_and_removes_stale_workspace(tmp_path: Path, monkeypatch):
    runs_root = tmp_path / "runs"
    monkeypatch.setenv("REPOMATE_RUNS_ROOT", str(runs_root))
    monkeypatch.delenv("REPOMATE_DATABASE_URL", raising=False)

    store = RunStore(runs_root)
    record = RunRecord(
        run_id="run_sweep",
        input=RepositoryInput(
            source=TaskSource.REPO_TASK,
            repo_url="https://github.com/a/b",
            task="document the thing",
        ),
    )
    store.save_run(record)
    workspace = store.workspace_dir(record.run_id)
    workspace.mkdir(parents=True)
    old = time.time() - 48 * 3600
    os.utime(workspace, (old, old))

    app = FastAPI()
    _sweep_stale_workspaces(app)

    assert app.state.swept_runs == [record.run_id]
    assert not workspace.exists()
