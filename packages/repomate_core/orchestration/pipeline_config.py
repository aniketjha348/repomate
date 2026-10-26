"""Pipeline configuration, sourced from the environment by default."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from repomate_core.contracts import (
    ModelBudgetLimits,
    RetrievalLimits,
    ToolLoopLimits,
)
from repomate_core.planning.types import Planner


def _env_int(name: str, default: int) -> int:
    try:
        value = int(os.environ.get(name, str(default)))
    except ValueError:
        return default
    return value if value > 0 else default


def _env_float(name: str, default: float) -> float:
    try:
        value = float(os.environ.get(name, str(default)))
    except ValueError:
        return default
    return value if value > 0 else default


def _retrieval_limits_from_env() -> RetrievalLimits:
    defaults = RetrievalLimits()
    return RetrievalLimits(
        max_files=_env_int("REPOMATE_RETRIEVAL_MAX_FILES", defaults.max_files),
        max_bytes_per_file=_env_int(
            "REPOMATE_RETRIEVAL_MAX_BYTES_PER_FILE", defaults.max_bytes_per_file
        ),
        max_total_bytes=_env_int(
            "REPOMATE_RETRIEVAL_MAX_TOTAL_BYTES", defaults.max_total_bytes
        ),
        max_search_results=_env_int(
            "REPOMATE_RETRIEVAL_MAX_SEARCH_RESULTS", defaults.max_search_results
        ),
        max_seconds=_env_float(
            "REPOMATE_RETRIEVAL_MAX_SECONDS", defaults.max_seconds
        ),
    )


def _model_limits_from_env() -> ModelBudgetLimits:
    defaults = ModelBudgetLimits()
    return ModelBudgetLimits(
        max_calls=_env_int("REPOMATE_MODEL_MAX_CALLS", defaults.max_calls),
        max_tokens=_env_int("REPOMATE_MODEL_MAX_TOKENS", defaults.max_tokens),
    )


def _tool_limits_from_env() -> ToolLoopLimits:
    defaults = ToolLoopLimits()
    return ToolLoopLimits(
        max_tool_calls=_env_int(
            "REPOMATE_TOOL_MAX_CALLS", defaults.max_tool_calls
        ),
        max_total_bytes=_env_int(
            "REPOMATE_TOOL_MAX_TOTAL_BYTES", defaults.max_total_bytes
        ),
        max_seconds=_env_float(
            "REPOMATE_TOOL_MAX_SECONDS", defaults.max_seconds
        ),
        max_results_per_search=_env_int(
            "REPOMATE_TOOL_MAX_RESULTS", defaults.max_results_per_search
        ),
    )


@dataclass
class PipelineConfig:
    runs_root: Path = field(
        default_factory=lambda: Path(os.environ.get("REPOMATE_RUNS_ROOT", "var/runs"))
    )
    github_token: Optional[str] = field(
        default_factory=lambda: os.environ.get("GITHUB_TOKEN") or None
    )
    keep_workspace: bool = field(
        default_factory=lambda: os.environ.get("REPOMATE_KEEP_WORKSPACE", "0") == "1"
    )
    max_run_seconds: float = field(
        default_factory=lambda: float(os.environ.get("REPOMATE_MAX_RUN_SECONDS", "900"))
    )
    sandbox_enabled: bool = field(
        default_factory=lambda: os.environ.get("REPOMATE_SANDBOX_ENABLED", "1") == "1"
    )
    retrieval_limits: RetrievalLimits = field(
        default_factory=_retrieval_limits_from_env
    )
    model_limits: ModelBudgetLimits = field(
        default_factory=_model_limits_from_env
    )
    tool_limits: ToolLoopLimits = field(
        default_factory=_tool_limits_from_env
    )
    database_url: Optional[str] = field(
        default_factory=lambda: os.environ.get("REPOMATE_DATABASE_URL") or None
    )
    planner: Optional[Planner] = None  # None => resolve from env/model config
