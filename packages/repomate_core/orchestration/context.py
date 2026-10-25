"""Per-run execution context: event emission, guards, finalization.

One :class:`RunContext` instance owns a run's record, its durable store
and the run-wide budgets. The pipeline is a sequence of stages that call
``emit`` for progress and ``guard`` between stages for cancellation and
deadline enforcement.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Callable, Optional

from repomate_core.contracts import (
    RepositoryInput,
    RunEvent,
    RunRecord,
    RunStatus,
    StageName,
    new_run_id,
    utcnow,
)
from repomate_core.orchestration.errors import RunCancelled
from repomate_core.orchestration.pipeline_config import PipelineConfig
from repomate_core.orchestration.store_factory import build_store

if TYPE_CHECKING:  # pragma: no cover - typing only
    from repomate_core.orchestration.store import RunStore
    from repomate_core.orchestration.store_sql import SqlRunStore

    StoreLike = "RunStore | SqlRunStore"

EventCallback = Callable[[RunEvent], None]


@dataclass
class RunContext:
    record: RunRecord
    store: "StoreLike"
    config: PipelineConfig
    started: float = field(default_factory=time.monotonic)
    event_cb: Optional[EventCallback] = None
    _seq: int = 0

    @classmethod
    def create(
        cls,
        run_input: RepositoryInput,
        config: PipelineConfig,
        run_id: Optional[str] = None,
        event_cb: Optional[EventCallback] = None,
    ) -> "RunContext":
        record = RunRecord(
            run_id=run_id or new_run_id(),
            input=run_input,
            status=RunStatus.RUNNING,
        )
        store = build_store(config.runs_root, config.database_url)
        store.save_run(record)
        return cls(record=record, store=store, config=config, event_cb=event_cb)

    # -- progress ----------------------------------------------------------

    def emit(self, stage: Optional[StageName], status: str, message: str) -> None:
        self._seq += 1
        event = RunEvent(seq=self._seq, stage=stage, status=status, message=message)  # type: ignore[arg-type]
        self.record.events.append(event)
        self.record.updated_at = utcnow()
        self.store.append_event(self.record.run_id, event)
        self.store.save_run(self.record)
        if self.event_cb:
            try:
                self.event_cb(event)
            except Exception:
                pass  # observer failures must never break a run

    # -- bounds --------------------------------------------------------------

    def guard(self) -> None:
        if self.store.cancel_requested(self.record.run_id):
            raise RunCancelled()
        elapsed = time.monotonic() - self.started
        if elapsed > self.config.max_run_seconds:
            from repomate_core.orchestration.errors import PipelineError
            from repomate_core.contracts import ErrorCode

            raise PipelineError(
                ErrorCode.TIMEOUT,
                f"run exceeded the {int(self.config.max_run_seconds)}s budget",
            )

    # -- workspace lifecycle ----------------------------------------------------

    @property
    def workspace_dir(self):
        return self.store.workspace_dir(self.record.run_id)

    def cleanup_workspace(self) -> bool:
        """Returns True when the workspace was kept for debugging."""
        keep = self.config.keep_workspace
        self.record.workspace_kept = keep
        if not keep:
            self.store.cleanup_workspace(self.record.run_id)
        return keep

    def persist(self) -> None:
        if self.record.artifact is not None and self.record.receipt is not None:
            self.store.save_artifact(
                self.record.run_id,
                self.record.artifact.patch,
                self.record.receipt.model_dump_json(indent=2),
            )
        self.record.updated_at = utcnow()
        self.store.save_run(self.record)
