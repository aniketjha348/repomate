"""Pipeline configuration, sourced from the environment by default."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from repomate_core.planning.types import Planner


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
    planner: Optional[Planner] = None  # None => resolve from env/model config
