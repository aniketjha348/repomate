"""Pipeline tasks executed by the worker."""

from __future__ import annotations

from repomate_core.contracts import RepositoryInput
from repomate_core.orchestration.pipeline import run_pipeline
from repomate_core.orchestration.pipeline_config import PipelineConfig
from services.worker.celery_app import app

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
    record = run_pipeline(
        RepositoryInput.model_validate(run_input),
        config=PipelineConfig(
            **{key: config[key] for key in _SERIALIZED_CONFIG_FIELDS if key in config}
        ),
        run_id=run_id,
    )
    return record.status.value
