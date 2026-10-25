# Worker service (Phase 4/5)

This directory will host the Celery worker entry point that executes
pipeline runs and the disposable verification sandbox.

Planned responsibilities (tracked in `docs/architecture.md`):

- **Phase 4** — sandboxed check execution: untrusted repository commands
  run inside a disposable environment with CPU / memory / disk / wall-time
  limits; results are captured as `VerificationCheck` records.
- **Phase 5** — durable job execution: Celery + Redis take over run
  dispatch from the API's in-process executor, with retries, concurrency
  limits and stale-workspace cleanup.

Nothing here is wired into the API yet, deliberately: the MVP executes
runs in-process and reports the test suite as `NOT_RUN` with an explicit
reason instead of pretending to have a sandbox.
