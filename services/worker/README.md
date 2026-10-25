# Worker service

Phase 4 delivered the verification sandbox itself
(`repomate_core.verification.sandbox`) — the API executes it in-process
today: untrusted repository test commands run with wall-time/CPU/memory
limits and a scrubbed environment, or report an honest `NOT_RUN`.

This directory hosts the **Phase 5** Celery worker that takes run
execution off the API process entirely:

- durable job dispatch via Redis (`REPOMATE_EXECUTION=celery`)
- bounded retries, per-worker concurrency limits
- stale-workspace sweeps

See `docs/architecture.md` for the execution-model seam that makes this
a drop-in replacement rather than a rewrite.
