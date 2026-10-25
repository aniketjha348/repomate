"""Celery application for durable background execution (Phase 5).

Broker: Redis (``REDIS_URL``). Tasks are acked late with prefetch 1 so a
crashed worker's run is retried rather than lost.
"""

from __future__ import annotations

import os

from celery import Celery

app = Celery(
    "repomate",
    broker=os.environ.get("REDIS_URL", "redis://localhost:6379/0"),
)
app.conf.update(
    task_track_started=True,
    worker_prefetch_multiplier=1,
    task_acks_late=True,
    task_reject_on_worker_lost=True,
)
if os.environ.get("CELERY_TASK_ALWAYS_EAGER", "") == "1":
    app.conf.task_always_eager = True
