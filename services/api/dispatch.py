"""Run dispatch: in-process thread (MVP) or Celery worker (Phase 5)."""

from __future__ import annotations

import asyncio

from fastapi import BackgroundTasks

from repomate_core.contracts import RepositoryInput, new_run_id
from repomate_core.orchestration.pipeline import run_pipeline
from repomate_core.orchestration.pipeline_config import PipelineConfig
from repomate_core.orchestration.store_factory import build_store
from services.api.config import read_settings
from services.api.routes.runs import _pipeline_config


def dispatch_run(
    background: BackgroundTasks,
    run_input: RepositoryInput,
    config: PipelineConfig,
    run_id: str,
) -> None:
    settings = read_settings()
    if settings.execution == "celery":
        from services.worker.tasks import execute_run

        execute_run.apply_async(
            args=[run_id, run_input.model_dump(mode="json"), _config_dict(config)]
        )
        return
    background.add_task(asyncio.to_thread, run_pipeline, run_input, config=config, run_id=run_id)


def _config_dict(config: PipelineConfig) -> dict:
    from pathlib import Path

    from services.worker.tasks import _SERIALIZED_CONFIG_FIELDS

    serialized: dict = {}
    for key in _SERIALIZED_CONFIG_FIELDS:
        value = getattr(config, key, None)
        if value is None:
            continue
        serialized[key] = str(value) if isinstance(value, Path) else value
    return serialized
