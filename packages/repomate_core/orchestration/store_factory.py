"""Store selection: filesystem by default, SQL when DATABASE_URL is set."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Union

from repomate_core.orchestration.store import RunStore
from repomate_core.orchestration.store_sql import SqlRunStore


def build_store(
    runs_root: Union[Path, str] = "",
    database_url: str | None = None,
) -> Union[RunStore, SqlRunStore]:
    """Both stores implement the same surface (save/load runs, events,
    artifacts, cancellation, workspace dirs, status counts, sweeps)."""
    database_url = database_url or os.environ.get("REPOMATE_DATABASE_URL", "").strip()
    root = Path(runs_root) if runs_root else Path(os.environ.get("REPOMATE_RUNS_ROOT", "var/runs"))
    if database_url:
        return SqlRunStore.from_database_url(database_url, runs_root=root)
    return RunStore(root)
