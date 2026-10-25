"""SQL-backed run store — the durable system of record (Phase 5).

One schema, two DB-API dialects:

- **SQLite** (``sqlite3``, stdlib): local development and the test suite
- **PostgreSQL** (``psycopg3``, when ``DATABASE_URL`` points at postgres):
  production

Run records and events are stored as JSON documents keyed by ``run_id``
(``status`` is denormalized for listing/metrics queries). Cancellation
markers live in a table so workers in other processes see them — that is
the whole point of moving off the filesystem for coordination state.
Workspace directories and patches remain derivable from the record, so
no blob storage is required for the MVP.
"""

from __future__ import annotations

import json
import re
import shutil
import sqlite3
from pathlib import Path
from typing import Optional
from urllib.parse import urlparse

from repomate_core.contracts import RunEvent, RunRecord

_SCHEMA = """
CREATE TABLE IF NOT EXISTS runs (
    run_id      TEXT PRIMARY KEY,
    status      TEXT NOT NULL,
    created_at  TEXT NOT NULL,
    updated_at  TEXT NOT NULL,
    record_json TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS run_events (
    run_id     TEXT NOT NULL,
    seq        INTEGER NOT NULL,
    event_json TEXT NOT NULL,
    PRIMARY KEY (run_id, seq)
);
CREATE TABLE IF NOT EXISTS run_cancels (
    run_id TEXT PRIMARY KEY
);
"""


def _translate_sqlite_to_pg(sql: str) -> str:
    """qmark → pyformat, for the psycopg dialect."""
    return re.sub(r"\?", "%s", sql)


class SqlRunStore:
    def __init__(self, connect, *, dialect: str, runs_root: Path) -> None:
        self._connect = connect
        self._dialect = dialect
        self._runs_root = Path(runs_root)
        with self._conn() as conn:
            self._execute_schema(conn)

    # -- constructors ------------------------------------------------------

    @classmethod
    def sqlite(cls, db_path: Path | str, *, runs_root: Path | str) -> "SqlRunStore":
        path = Path(db_path)
        path.parent.mkdir(parents=True, exist_ok=True)

        def connect() -> sqlite3.Connection:
            conn = sqlite3.connect(str(path), timeout=30)
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA busy_timeout=30000")
            return conn

        return cls(connect, dialect="sqlite", runs_root=runs_root)

    @classmethod
    def from_database_url(
        cls, database_url: str, *, runs_root: Path | str
    ) -> "SqlRunStore":
        parsed = urlparse(database_url)
        if parsed.scheme in ("sqlite", "sqlite3"):
            path = parsed.path.lstrip("/") or str(Path(runs_root) / "runs.db")
            return cls.sqlite("/" + path if not Path(path).is_absolute() else path, runs_root=runs_root)
        if parsed.scheme in ("postgres", "postgresql"):
            try:
                import psycopg
            except ImportError as exc:  # pragma: no cover - env-dependent
                raise RuntimeError(
                    "DATABASE_URL points at PostgreSQL but psycopg is not "
                    "installed; add the 'worker' extra or use SQLite"
                ) from exc

            def connect():
                return psycopg.connect(database_url)

            return cls(connect, dialect="postgresql", runs_root=runs_root)
        raise ValueError(f"unsupported DATABASE_URL scheme: {parsed.scheme!r}")

    # -- connection plumbing -------------------------------------------------

    class _Conn:
        def __init__(self, inner, dialect: str) -> None:
            self.inner = inner
            self.dialect = dialect
            self._cursor = None

        def execute(self, sql: str, params: tuple = ()) -> None:
            if self.dialect == "postgresql":
                sql = _translate_sqlite_to_pg(sql)
            self._cursor = self.inner.execute(sql, params)

        def fetchall(self) -> list[tuple]:
            if self._cursor is None:
                return []
            return self._cursor.fetchall()

        def commit(self) -> None:
            self.inner.commit()

    def _conn(self) -> "_ConnContext":
        return _ConnContext(self._connect(), self._dialect)

    def _execute_schema(self, conn) -> None:
        for statement in filter(None, (s.strip() for s in _SCHEMA.split(";"))):
            conn.inner.execute(statement)

    # -- run records ------------------------------------------------------------

    def save_run(self, record: RunRecord) -> None:
        payload = record.model_dump_json()
        with self._conn() as conn:
            conn.execute(
                "INSERT INTO runs (run_id, status, created_at, updated_at, record_json) "
                "VALUES (?, ?, ?, ?, ?) "
                "ON CONFLICT(run_id) DO UPDATE SET "
                "status=excluded.status, updated_at=excluded.updated_at, "
                "record_json=excluded.record_json",
                (record.run_id, record.status.value, record.created_at.isoformat(),
                 record.updated_at.isoformat(), payload),
            )

    def load_run(self, run_id: str) -> Optional[RunRecord]:
        with self._conn() as conn:
            conn.execute("SELECT record_json FROM runs WHERE run_id = ?", (run_id,))
            row = conn.fetchall()
        if not row:
            return None
        try:
            return RunRecord.model_validate_json(row[0][0])
        except ValueError:
            return None

    def list_run_ids(self) -> list[str]:
        with self._conn() as conn:
            conn.execute("SELECT run_id FROM runs ORDER BY run_id")
            return [row[0] for row in conn.fetchall()]

    def status_counts(self) -> dict[str, int]:
        with self._conn() as conn:
            conn.execute("SELECT status, COUNT(*) FROM runs GROUP BY status")
            return {row[0]: row[1] for row in conn.fetchall()}

    # -- events -----------------------------------------------------------------

    def append_event(self, run_id: str, event: RunEvent) -> None:
        with self._conn() as conn:
            conn.execute(
                "INSERT INTO run_events (run_id, seq, event_json) VALUES (?, ?, ?) "
                "ON CONFLICT(run_id, seq) DO UPDATE SET event_json=excluded.event_json",
                (run_id, event.seq, event.model_dump_json()),
            )

    def load_events(self, run_id: str, *, after_seq: int = 0) -> list[RunEvent]:
        with self._conn() as conn:
            conn.execute(
                "SELECT seq, event_json FROM run_events "
                "WHERE run_id = ? AND seq > ? ORDER BY seq",
                (run_id, after_seq),
            )
            rows = conn.fetchall()
        events: list[RunEvent] = []
        for _seq, payload in rows:
            try:
                events.append(RunEvent.model_validate_json(payload))
            except ValueError:
                continue
        return events

    # -- artifacts & cancellation --------------------------------------------------

    def read_artifact(self, run_id: str) -> Optional[str]:
        record = self.load_run(run_id)
        if record is None or record.artifact is None or record.receipt is None:
            return None
        return record.artifact.patch

    def save_artifact(self, run_id: str, patch: str, receipt_json: str) -> None:
        # Artifacts live inside the record JSON (save_run already wrote
        # them); this method exists so callers can treat every store alike.
        _ = run_id, patch, receipt_json

    def request_cancel(self, run_id: str) -> bool:
        if self.load_run(run_id) is None:
            return False
        with self._conn() as conn:
            conn.execute(
                "INSERT OR IGNORE INTO run_cancels (run_id) VALUES (?)", (run_id,)
            )
        return True

    def cancel_requested(self, run_id: str) -> bool:
        with self._conn() as conn:
            conn.execute("SELECT 1 FROM run_cancels WHERE run_id = ?", (run_id,))
            return bool(conn.fetchall())

    # -- workspaces (filesystem, as before) ---------------------------------------------

    def workspace_dir(self, run_id: str) -> Path:
        if "/" in run_id or "\\" in run_id or run_id in ("", ".", ".."):
            raise ValueError(f"invalid run id: {run_id!r}")
        return self._runs_root / run_id

    def cleanup_workspace(self, run_id: str) -> None:
        workspace = self.workspace_dir(run_id) / "workspace"
        if workspace.exists():
            shutil.rmtree(workspace, ignore_errors=True)

    # -- maintenance ----------------------------------------------------------------------

    def sweep_stale_workspaces(self, *, max_age_hours: float = 24.0) -> list[str]:
        """Delete workspace directories of terminal runs older than the cap."""
        import time

        removed: list[str] = []
        cutoff = time.time() - max_age_hours * 3600
        for run_id in self.list_run_ids():
            workspace = self.workspace_dir(run_id) / "workspace"
            if workspace.exists() and workspace.stat().st_mtime < cutoff:
                self.cleanup_workspace(run_id)
                removed.append(run_id)
        return removed

    def dump_json(self, value) -> str:
        return json.dumps(value, indent=2, default=str)


class _ConnContext:
    def __init__(self, inner, dialect: str) -> None:
        self.conn = SqlRunStore._Conn(inner, dialect)

    def __enter__(self) -> "SqlRunStore._Conn":
        return self.conn

    def __exit__(self, *exc_info) -> None:
        try:
            if not any(exc_info):
                self.conn.commit()
        finally:
            self.conn.inner.close()
