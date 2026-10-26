"""File-backed run store (Phase 5 swaps this for PostgreSQL).

Layout under ``<root>/<run_id>/``::

    run.json       full RunRecord (source of truth for GET /runs/{id})
    events.jsonl   append-only progress events (SSE replays from here)
    patch.diff     the generated artifact
    receipt.json   verification receipt
    CANCEL         cancellation marker (cooperative, checked between stages)
    workspace/     the cloned snapshot (deleted unless keep_workspace)
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Optional

from repomate_core.contracts import RunEvent, RunRecord, RunStatus


class RunStore:
    def __init__(self, root: Path | str) -> None:
        self.root = Path(root)

    # -- layout ----------------------------------------------------------

    def run_dir(self, run_id: str) -> Path:
        if "/" in run_id or "\\" in run_id or run_id in ("", ".", ".."):
            raise ValueError(f"invalid run id: {run_id!r}")
        return self.root / run_id

    def list_run_ids(self) -> list[str]:
        if not self.root.exists():
            return []
        return sorted(
            p.name for p in self.root.iterdir() if (p / "run.json").is_file()
        )

    # -- run record --------------------------------------------------------

    def save_run(self, record: RunRecord) -> None:
        path = self.run_dir(record.run_id) / "run.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(record.model_dump_json(indent=2), encoding="utf-8")

    def load_run(self, run_id: str) -> Optional[RunRecord]:
        path = self.run_dir(run_id) / "run.json"
        if not path.is_file():
            return None
        try:
            return RunRecord.model_validate_json(path.read_text(encoding="utf-8"))
        except ValueError:
            return None

    # -- events ------------------------------------------------------------

    def append_event(self, run_id: str, event: RunEvent) -> None:
        path = self.run_dir(run_id) / "events.jsonl"
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as handle:
            handle.write(event.model_dump_json() + "\n")

    def load_events(self, run_id: str, *, after_seq: int = 0) -> list[RunEvent]:
        path = self.run_dir(run_id) / "events.jsonl"
        if not path.is_file():
            return []
        events: list[RunEvent] = []
        for line in path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            try:
                event = RunEvent.model_validate_json(line)
            except ValueError:
                continue
            if event.seq > after_seq:
                events.append(event)
        return events

    # -- artifacts ---------------------------------------------------------

    def save_artifact(self, run_id: str, patch: str, receipt_json: str) -> Path:
        run_dir = self.run_dir(run_id)
        run_dir.mkdir(parents=True, exist_ok=True)
        (run_dir / "patch.diff").write_text(patch, encoding="utf-8", newline="\n")
        (run_dir / "receipt.json").write_text(receipt_json, encoding="utf-8")
        return run_dir / "patch.diff"

    def artifact_path(self, run_id: str) -> Optional[Path]:
        path = self.run_dir(run_id) / "patch.diff"
        return path if path.is_file() else None

    # -- cancellation & cleanup ---------------------------------------------

    def request_cancel(self, run_id: str) -> bool:
        if not self.run_dir(run_id).exists():
            return False
        (self.run_dir(run_id) / "CANCEL").touch()
        return True

    def cancel_requested(self, run_id: str) -> bool:
        return (self.run_dir(run_id) / "CANCEL").is_file()

    def cleanup_workspace(self, run_id: str) -> None:
        workspace = self.run_dir(run_id) / "workspace"
        if workspace.exists():
            shutil.rmtree(workspace, ignore_errors=True)

    def workspace_dir(self, run_id: str) -> Path:
        return self.run_dir(run_id) / "workspace"

    # -- helpers -------------------------------------------------------------

    def record_status(self, run_id: str) -> Optional[RunStatus]:
        record = self.load_run(run_id)
        return record.status if record else None

    def dump_json(self, value) -> str:
        return json.dumps(value, indent=2, default=str)

    # -- uniform surface shared with SqlRunStore --------------------------------

    def read_artifact(self, run_id: str) -> Optional[str]:
        path = self.artifact_path(run_id)
        if path is None:
            return None
        return path.read_text(encoding="utf-8")

    def status_counts(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        for run_id in self.list_run_ids():
            record = self.load_run(run_id)
            if record:
                counts[record.status.value] = counts.get(record.status.value, 0) + 1
        return counts

    def count_active_runs(self) -> int:
        """Count runs that still hold an execution slot.

        ``PENDING`` counts after admission and before the worker starts;
        ``RUNNING`` counts while the pipeline executes. Used by API fair-use
        admission to cap concurrent work.
        """
        return sum(
            1
            for run_id in self.list_run_ids()
            if (record := self.load_run(run_id)) is not None
            and record.status in (RunStatus.PENDING, RunStatus.RUNNING)
        )

    def sweep_stale_workspaces(self, *, max_age_hours: float = 24.0) -> list[str]:
        """Delete workspace directories of terminal runs older than the cap."""
        import time

        removed: list[str] = []
        cutoff = time.time() - max_age_hours * 3600
        for run_id in self.list_run_ids():
            # ``workspace_dir`` already returns ``<run_id>/workspace``.
            workspace = self.workspace_dir(run_id)
            if workspace.exists() and workspace.stat().st_mtime < cutoff:
                self.cleanup_workspace(run_id)
                removed.append(run_id)
        return removed

    def reconcile_stale_runs(self) -> list[str]:
        """Close out runs left RUNNING/PENDING by a previous process.

        In-process execution cannot survive a restart, so a run that was
        mid-flight when the process died would report RUNNING forever and
        the UI would poll a run that can never move. Mark them FAILED with
        an explicit reason: an honest terminal state beats a permanent lie.
        """
        from repomate_core.contracts import ErrorCode, RunError, RunStatus

        reconciled: list[str] = []
        for run_id in self.list_run_ids():
            record = self.load_run(run_id)
            if record is None or record.is_terminal:
                continue
            record.status = RunStatus.FAILED
            record.error = RunError(
                code=ErrorCode.INTERNAL,
                message=(
                    "run was interrupted by a process restart and never "
                    "reached a terminal state"
                ),
                detail=(
                    "RepoMate reconciled this run at startup. With in-process "
                    "execution a restart loses the worker thread, so the run "
                    "cannot be resumed; re-submit the task to retry."
                ),
            )
            self.save_run(record)
            self.cleanup_workspace(run_id)
            reconciled.append(run_id)
        return reconciled
