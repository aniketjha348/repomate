"""Celery application for durable background execution (Phase 5).

Broker: Redis (``REDIS_URL``). Tasks are acked late with prefetch 1 so a
crashed worker's run is retried rather than lost.
"""

from __future__ import annotations

import os

from celery import Celery

from repomate_core.env import load_env_file

# The worker is its own process: it needs the same ``.env`` the API reads,
# otherwise a worker started from a shell without exported variables would
# silently fall back to the heuristic planner.
load_env_file()


def _env_positive_float(name: str, default: float) -> float:
    try:
        value = float(os.environ.get(name, str(default)))
    except ValueError:
        return default
    return value if value > 0 else default


def _env_positive_int(name: str, default: int) -> int:
    try:
        value = int(os.environ.get(name, str(default)))
    except ValueError:
        return default
    return value if value > 0 else default


# Celery is the hard backstop behind the pipeline's cooperative wall-clock
# guard: a soft limit is raised inside the task (so the run can be finalised
# honestly), and a hard limit kills a genuinely wedged child.
_MAX_RUN_SECONDS = _env_positive_float("REPOMATE_MAX_RUN_SECONDS", 900.0)
_HARD_TIME_LIMIT = _MAX_RUN_SECONDS + max(30.0, _MAX_RUN_SECONDS * 0.1)
_WORKER_CONCURRENCY = _env_positive_int(
    "REPOMATE_WORKER_CONCURRENCY",
    _env_positive_int("REPOMATE_MAX_CONCURRENT_RUNS", 3),
)


app = Celery(
    "repomate",
    broker=os.environ.get("REDIS_URL", "redis://localhost:6379/0"),
    # The worker process must import the task module, otherwise Celery
    # discards deliveries with "unregistered task".
    include=["services.worker.tasks"],
)
app.conf.update(
    task_track_started=True,
    worker_prefetch_multiplier=1,
    task_acks_late=True,
    task_reject_on_worker_lost=True,
    task_soft_time_limit=_MAX_RUN_SECONDS,
    task_time_limit=_HARD_TIME_LIMIT,
    worker_concurrency=_WORKER_CONCURRENCY,
)
if os.environ.get("CELERY_TASK_ALWAYS_EAGER", "") == "1":
    app.conf.task_always_eager = True
