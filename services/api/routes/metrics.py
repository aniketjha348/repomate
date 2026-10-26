"""Operational metrics (counts by status and planner)."""

from __future__ import annotations

from fastapi import APIRouter

from repomate_core.orchestration.store_factory import build_store
from services.api import fair_use
from services.api.config import read_settings

router = APIRouter()

_STARTED_AT = None


def _started_at() -> str:
    global _STARTED_AT
    if _STARTED_AT is None:
        from repomate_core.contracts import utcnow

        _STARTED_AT = utcnow().isoformat()
    return _STARTED_AT


@router.get("/api/metrics")
def metrics() -> dict:
    settings = read_settings()
    store = build_store(settings.runs_root, settings.database_url)

    planner_counts: dict[str, int] = {}
    for run_id in store.list_run_ids():
        record = store.load_run(run_id)
        if record and record.planner:
            planner_counts[record.planner] = planner_counts.get(record.planner, 0) + 1

    # Aggregate operational counters only. Do not expose filesystem paths,
    # environment contents, prompts or per-run identifiers here: the route is
    # reachable without authentication in the default deployment.
    return {
        "runs_by_status": store.status_counts(),
        "runs_by_planner": planner_counts,
        "fair_use": fair_use.metrics_snapshot(settings, store),
        "execution": settings.execution,
        "sandbox_enabled": settings.sandbox_enabled,
        "process_started_at": _started_at(),
    }
