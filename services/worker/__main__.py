"""``python -m services.worker`` starts a run-execution worker."""

from __future__ import annotations

import os

from services.worker.celery_app import app

if __name__ == "__main__":
    argv = [
        "worker",
        "--loglevel=info",
        f"--concurrency={os.environ.get('REPOMATE_WORKER_CONCURRENCY', '2')}",
    ]
    app.worker_main(argv=argv)
