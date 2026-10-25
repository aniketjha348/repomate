# RepoMate

**Evidence-first open-source contribution agent.**

A developer gives RepoMate a public GitHub issue URL (or a repository URL plus a
development task). RepoMate inspects the repository, locates relevant evidence,
builds a contribution plan, produces a suitable artifact (today: a documentation
diff), and reports **actual** verification results — with honest limitations,
never fabricated ones.

Out of scope for the MVP (deliberately): automatic issue discovery, submitting
PRs to GitHub, multi-agent orchestration. PS04's contribution workflow comes
first; enterprise capabilities exist to make that workflow reliable and secure.

## Status

| Phase | Scope | State |
|---|---|---|
| 1 | Contracts + architecture | done |
| 2 | Working Python core + vertical slice (docs task → real diff → receipt) | done |
| 3 | Web experience (Next.js workspace) | in progress (frontend delivered in this push) |
| 4 | Verification sandbox (process backend: wall-time/CPU/memory limits, env scrubbing) | done |
| 5 | Celery/Redis workers, PostgreSQL, monitoring | not started |
| 6 | PS04 evaluation matrix | pending slice hardening |

The AI planner is provider-independent. With `VYCE_API_KEY` set, plans come
from the Vyce AI gateway (DeepSeek); without it, a deterministic heuristic
planner runs and **every artifact is labelled with the planner identity**, so
reports never overstate what produced them.

## Deployment

Two platforms, one repository:

- **Frontend** — `apps/web` (Next.js) on **Vercel**: import the repo with root
  directory `apps/web`, set `NEXT_PUBLIC_API_URL` to the Render URL.
- **Backend** — the FastAPI service on **Render** (Docker image
  `deploy/Dockerfile.api`, blueprint `render.yaml`): it shells out to `git`
  for shallow clones, which serverless platforms cannot do — hence Render.
- Secrets (`VYCE_API_KEY`, `GITHUB_TOKEN`, `ALLOWED_ORIGINS`) are set in the
  Render dashboard; `ALLOWED_ORIGINS` must exactly match the Vercel origin.

Full runbook: [docs/deployment.md](docs/deployment.md).

## Quickstart

Requires Python ≥ 3.10 and git.

```bash
python -m venv .venv
source .venv/Scripts/activate   # Git Bash on Windows
# .venv\Scripts\activate        # cmd/PowerShell

pip install -e ".[dev,api]"

# hermetic test suite (no network)
pytest

# one end-to-end run against a licensed public repository
python scripts/run_task.py \
  --repo https://github.com/psf/black \
  --task "Add documentation for how to exclude directories from formatting to the README"

# HTTP API (SSE progress, artifact download)
uvicorn services.api.main:app --reload
```

Copy `.env.example` to `.env` to configure the model gateway, an optional
`GITHUB_TOKEN` (raises the 60 req/h unauthenticated REST limit), and run
budgets.

## Layout

```
apps/web/            Next.js frontend (App Router + TypeScript; deploys to Vercel)
services/api/        FastAPI app
services/worker/     Celery + sandbox entry point (Phase 4/5)
packages/repomate_core/   the engine: repository, evidence, planning,
                          models, artifacts, verification, safety, orchestration
tests/               unit / integration (hermetic) / e2e (opt-in network)
deploy/              Dockerfiles + compose
docs/                architecture, security, evaluation, product requirements
```

API and worker share `repomate_core`; no business logic is duplicated per
surface.

## HTTP API (MVP)

| Route | Purpose |
|---|---|
| `POST /api/runs` | start a run (`issue_url`, or `repo_url` + `task`) |
| `GET /api/runs/{id}` | full run record (snapshot, evidence, plan, receipt) |
| `GET /api/runs/{id}/events` | SSE progress stream |
| `GET /api/runs/{id}/artifacts/patch` | download the generated patch |
| `POST /api/runs/{id}/cancel` | cooperative cancellation |
| `GET /api/health` | liveness + active planner identity |

Run records survive server restarts (file-backed store today; PostgreSQL is
the Phase 5 system of record), so refreshing the browser mid-run loses
nothing.

## Honest verification model

Every run ends with a receipt. `PASSED`/`FAILED` only ever come from checks
that actually executed (e.g. `git apply --check` against the pinned commit, or
a deterministic policy evaluation). Anything not executed is `NOT_RUN` with an
explicit reason — e.g. the repository test suite until the Phase 4 sandbox
exists.
