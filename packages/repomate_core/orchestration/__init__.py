"""Run orchestration: the end-to-end pipeline and its durable store."""

from repomate_core.orchestration.context import EventCallback, RunContext
from repomate_core.orchestration.errors import PipelineError, RunCancelled
from repomate_core.orchestration.pipeline import (
    github_workspace_factory,
    resolve_planner,
    run_pipeline,
)
from repomate_core.orchestration.pipeline_config import PipelineConfig
from repomate_core.orchestration.store import RunStore
from repomate_core.orchestration.store_factory import build_store
from repomate_core.orchestration.store_sql import SqlRunStore

__all__ = [
    "EventCallback",
    "PipelineConfig",
    "PipelineError",
    "RunCancelled",
    "RunContext",
    "RunStore",
    "SqlRunStore",
    "build_store",
    "github_workspace_factory",
    "resolve_planner",
    "run_pipeline",
]
