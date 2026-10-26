"""Pipeline tasks executed by the worker."""

from __future__ import annotations

import logging

from celery.exceptions import SoftTimeLimitExceeded

from repomate_core.contracts import ErrorCode, RepositoryInput, RunError, RunStatus
from repomate_core.orchestration.pipeline import run_pipeline
from repomate_core.orchestration.pipeline_config import PipelineConfig
from repomate_core.orchestration.store_factory import build_store
from services.worker.celery_app import app

logger = logging.getLogger(__name__)

_SERIALIZED_CONFIG_FIELDS = (
    "runs_root",
    "database_url",
    "github_token",
    "keep_workspace",
    "max_run_seconds",
    "sandbox_enabled",
)


@app.task(name="repomate.execute_run", bind=True, max_retries=1)
def execute_run(self, run_id: str, run_input: dict, config: dict) -> str:
    """Run one contribution pipeline; returns the terminal status."""
    pipeline_config = PipelineConfig(
        **{key: config[key] for key in _SERIALIZED_CONFIG_FIELDS if key in config}
    )
    try:
        record = run_pipeline(
            RepositoryInput.model_validate(run_input),
            config=pipeline_config,
            run_id=run_id,
        )
    except SoftTimeLimitExceeded:
        # The soft limit normally surfaces inside run_pipeline and is mapped
        # to a terminal FAILED/TIMEOUT record. If it lands while the record is
        # being finalised, close the run here rather than leaving RUNNING.
        _mark_timed_out(run_id, pipeline_config)
        return RunStatus.FAILED.value
    return record.status.value


def _mark_timed_out(run_id: str, config: PipelineConfig) -> None:
    try:
        store = build_store(config.runs_root, config.database_url)
        record = store.load_run(run_id)
        if record is None or record.is_terminal:
            return
        record.status = RunStatus.FAILED
        record.error = RunError(
            code=ErrorCode.TIMEOUT,
            message=(
                f"worker exceeded the {config.max_run_seconds:g}s run time "
                "limit"
            ),
            detail=(
                "The Celery worker's soft time limit interrupted the pipeline "
                "before it could publish a receipt. No verification result is "
                "claimed."
            ),
        )
        store.save_run(record)
        store.cleanup_workspace(run_id)
    except Exception:  # noqa: BLE001 - already on the failure path
        logger.exception("could not record the worker timeout for %s", run_id)
