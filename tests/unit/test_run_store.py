"""File-backed run store maintenance (cross-platform)."""

from __future__ import annotations

import os
import time
from pathlib import Path

from repomate_core.contracts import (
    RepositoryInput,
    RunRecord,
    TaskSource,
)
from repomate_core.orchestration.store import RunStore


def _record(run_id: str = "run_t1") -> RunRecord:
    return RunRecord(
        run_id=run_id,
        input=RepositoryInput(
            source=TaskSource.REPO_TASK,
            repo_url="https://github.com/a/b",
            task="document the thing",
        ),
    )


def test_sweep_stale_workspaces_removes_old_workspace(tmp_path: Path):
    store = RunStore(tmp_path / "runs")
    record = _record()
    store.save_run(record)

    workspace = store.workspace_dir(record.run_id)
    workspace.mkdir(parents=True)
    (workspace / "file.txt").write_text("x", encoding="utf-8")
    old = time.time() - 48 * 3600
    os.utime(workspace, (old, old))

    removed = store.sweep_stale_workspaces(max_age_hours=24)

    assert removed == [record.run_id]
    assert not workspace.exists()
    assert store.load_run(record.run_id) is not None  # run record survives


def test_sweep_keeps_fresh_workspace(tmp_path: Path):
    store = RunStore(tmp_path / "runs")
    record = _record()
    store.save_run(record)

    workspace = store.workspace_dir(record.run_id)
    workspace.mkdir(parents=True)

    assert store.sweep_stale_workspaces(max_age_hours=24) == []
    assert workspace.exists()
