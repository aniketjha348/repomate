"""Phase 5 TDD: SQL-backed run store (PostgreSQL in production, SQLite in
tests via the same DB-API surface). The durable system of record."""

from pathlib import Path
from urllib.parse import urlparse

import pytest

from repomate_core.contracts import (
    RepositoryInput,
    RunEvent,
    RunRecord,
    RunStatus,
    TaskSource,
)
from repomate_core.orchestration.store_sql import SqlRunStore, _sqlite_path


def _record(run_id: str = "run_t1") -> RunRecord:
    return RunRecord(
        run_id=run_id,
        input=RepositoryInput(
            source=TaskSource.REPO_TASK,
            repo_url="https://github.com/a/b",
            task="document the thing",
        ),
        status=RunStatus.RUNNING,
    )


@pytest.fixture
def store(tmp_path: Path) -> SqlRunStore:
    return SqlRunStore.sqlite(tmp_path / "runs.db", runs_root=tmp_path / "ws")


class TestSqliteUrlResolution:
    def test_relative_three_slash_url_stays_relative(self, tmp_path):
        path = _sqlite_path(urlparse("sqlite:///var/runs.db"), tmp_path)
        assert path == Path("var/runs.db")

    def test_absolute_four_slash_url_stays_absolute(self, tmp_path):
        path = _sqlite_path(urlparse("sqlite:////tmp/runs.db"), tmp_path)
        assert path == Path("/tmp/runs.db")

    def test_empty_url_falls_back_to_runs_root(self, tmp_path):
        path = _sqlite_path(urlparse("sqlite://"), tmp_path)
        assert path == tmp_path / "runs.db"


class TestRunRecords:
    def test_save_and_load_round_trip(self, store):
        record = _record()
        store.save_run(record)
        loaded = store.load_run("run_t1")
        assert loaded == record

    def test_missing_run_returns_none(self, store):
        assert store.load_run("run_ghost") is None

    def test_save_is_upsert(self, store):
        record = _record()
        store.save_run(record)
        record.status = RunStatus.COMPLETED
        store.save_run(record)
        assert store.list_run_ids() == ["run_t1"]
        assert store.load_run("run_t1").status is RunStatus.COMPLETED

    def test_list_run_ids_sorted(self, store):
        for rid in ("run_b", "run_a", "run_c"):
            store.save_run(_record(rid))
        assert store.list_run_ids() == ["run_a", "run_b", "run_c"]

    def test_persists_across_instances(self, tmp_path):
        first = SqlRunStore.sqlite(tmp_path / "runs.db", runs_root=tmp_path)
        first.save_run(_record())
        second = SqlRunStore.sqlite(tmp_path / "runs.db", runs_root=tmp_path)
        assert second.load_run("run_t1") is not None


class TestEvents:
    def test_append_and_load_with_after_seq(self, store):
        store.save_run(_record())
        for seq in (1, 2, 3):
            store.append_event("run_t1", RunEvent(seq=seq, status="INFO", message=f"m{seq}"))
        assert [e.seq for e in store.load_events("run_t1")] == [1, 2, 3]
        assert [e.seq for e in store.load_events("run_t1", after_seq=2)] == [3]
        assert store.load_events("run_missing") == []


class TestArtifactsAndCancellation:
    def test_read_artifact_from_record(self, store):
        from repomate_core.contracts import (
            ArtifactKind,
            ContributionArtifact,
            VerificationReceipt,
            VerificationStatus,
        )

        record = _record()
        record.artifact = ContributionArtifact(
            kind=ArtifactKind.DOCS_DIFF,
            patch="diff --git a/README.md b/README.md\n",
            affected_paths=["README.md"],
            based_on_commit="a" * 40,
            generated_by="heuristic-v1",
        )
        record.receipt = VerificationReceipt(
            checks=[], overall=VerificationStatus.PASSED, environment="test"
        )
        store.save_run(record)
        assert "diff --git" in (store.read_artifact("run_t1") or "")
        assert store.read_artifact("run_t2") is None

    def test_cancellation_round_trip(self, store):
        store.save_run(_record())
        assert store.cancel_requested("run_t1") is False
        assert store.request_cancel("run_t1") is True
        assert store.cancel_requested("run_t1") is True

    def test_workspace_dirs_on_filesystem(self, store, tmp_path):
        # The clone destination must match the file store's contract.
        assert store.workspace_dir("run_t1") == tmp_path / "ws" / "run_t1" / "workspace"
        clone = store.workspace_dir("run_t1")
        clone.mkdir(parents=True)
        (clone / "file.txt").write_text("x", encoding="utf-8")
        store.cleanup_workspace("run_t1")
        assert not clone.exists()
        assert store.workspace_dir("run_t1").parent.exists()  # run dir survives
