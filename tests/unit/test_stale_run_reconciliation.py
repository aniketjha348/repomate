"""Startup reconciliation of runs orphaned by a process restart.

With in-process execution (the default) a restart kills the worker thread,
so a run that was mid-flight would report RUNNING forever and the UI would
poll a run that can never move. Startup must close those out with an honest
terminal state — the same principle as the ``NOT_RUN`` receipt checks.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi import FastAPI

from repomate_core.contracts import (
    ErrorCode,
    RepositoryInput,
    RunRecord,
    RunStatus,
    TaskSource,
)
from repomate_core.orchestration.store import RunStore
from repomate_core.orchestration.store_sql import SqlRunStore
from services.api.app import _reconcile_stale_runs

RUNNING = RunStatus.RUNNING


def _record(run_id: str, status: RunStatus) -> RunRecord:
    return RunRecord(
        run_id=run_id,
        status=status,
        input=RepositoryInput(
            source=TaskSource.REPO_TASK,
            repo_url="https://github.com/a/b",
            task="document the thing",
        ),
    )


class TestFileStoreReconciliation:
    def _store(self, tmp_path: Path) -> RunStore:
        return RunStore(tmp_path / "runs")

    def test_running_run_is_failed_with_a_reason(self, tmp_path):
        store = self._store(tmp_path)
        store.save_run(_record("run_stuck", RUNNING))

        reconciled = store.reconcile_stale_runs()

        assert reconciled == ["run_stuck"]
        record = store.load_run("run_stuck")
        assert record.status is RunStatus.FAILED
        assert record.error is not None
        assert record.error.code is ErrorCode.INTERNAL
        assert "restart" in record.error.message

    def test_pending_run_is_reconciled_too(self, tmp_path):
        store = self._store(tmp_path)
        store.save_run(_record("run_pending", RunStatus.PENDING))

        assert store.reconcile_stale_runs() == ["run_pending"]
        assert store.load_run("run_pending").status is RunStatus.FAILED

    @pytest.mark.parametrize(
        "status",
        [RunStatus.COMPLETED, RunStatus.FAILED, RunStatus.CANCELLED, RunStatus.NEED_MORE_INFO, RunStatus.PARTIAL],
    )
    def test_terminal_runs_are_left_alone(self, tmp_path, status):
        store = self._store(tmp_path)
        store.save_run(_record("run_done", status))

        assert store.reconcile_stale_runs() == []
        assert store.load_run("run_done").status is status

    def test_orphaned_workspace_is_cleaned_up(self, tmp_path):
        store = self._store(tmp_path)
        store.save_run(_record("run_stuck", RUNNING))
        workspace = store.workspace_dir("run_stuck")
        workspace.mkdir(parents=True)
        (workspace / "file.txt").write_text("x", encoding="utf-8")

        store.reconcile_stale_runs()

        assert not workspace.exists()

    def test_is_idempotent(self, tmp_path):
        store = self._store(tmp_path)
        store.save_run(_record("run_stuck", RUNNING))

        assert store.reconcile_stale_runs() == ["run_stuck"]
        assert store.reconcile_stale_runs() == []


class TestSqlStoreReconciliation:
    def test_running_run_is_failed(self, tmp_path):
        store = SqlRunStore.sqlite(tmp_path / "runs.db", runs_root=tmp_path / "ws")
        store.save_run(_record("run_stuck", RUNNING))

        assert store.reconcile_stale_runs() == ["run_stuck"]
        record = store.load_run("run_stuck")
        assert record.status is RunStatus.FAILED
        assert record.error.code is ErrorCode.INTERNAL

    def test_terminal_run_untouched(self, tmp_path):
        store = SqlRunStore.sqlite(tmp_path / "runs.db", runs_root=tmp_path / "ws")
        store.save_run(_record("run_done", RunStatus.COMPLETED))

        assert store.reconcile_stale_runs() == []
        assert store.load_run("run_done").status is RunStatus.COMPLETED


class TestApiStartupReconciliation:
    def test_startup_closes_orphaned_runs(self, tmp_path, monkeypatch):
        runs_root = tmp_path / "runs"
        monkeypatch.setenv("REPOMATE_RUNS_ROOT", str(runs_root))
        monkeypatch.delenv("REPOMATE_DATABASE_URL", raising=False)
        monkeypatch.delenv("REPOMATE_RECONCILE_STALE_RUNS", raising=False)

        store = RunStore(runs_root)
        store.save_run(_record("run_stuck", RUNNING))

        app = FastAPI()
        _reconcile_stale_runs(app)

        assert app.state.reconciled_runs == ["run_stuck"]
        assert store.load_run("run_stuck").status is RunStatus.FAILED

    def test_reconciliation_can_be_disabled(self, tmp_path, monkeypatch):
        runs_root = tmp_path / "runs"
        monkeypatch.setenv("REPOMATE_RUNS_ROOT", str(runs_root))
        monkeypatch.setenv("REPOMATE_RECONCILE_STALE_RUNS", "0")
        monkeypatch.delenv("REPOMATE_DATABASE_URL", raising=False)

        store = RunStore(runs_root)
        store.save_run(_record("run_stuck", RUNNING))

        app = FastAPI()
        _reconcile_stale_runs(app)

        assert not hasattr(app.state, "reconciled_runs")
        assert store.load_run("run_stuck").status is RUNNING
