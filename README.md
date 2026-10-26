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
| 3 | Web experience (Next.js workspace) | done |
| 4 | Verification sandbox (process backend: wall-time/CPU/memory limits, env scrubbing) | done |
| 5 | Durable execution: SQL run store (SQLite→PostgreSQL), Celery worker + Redis, metrics, stale-workspace sweeps | done (in-process mode remains the default) |
| 6 | PS04 evaluation matrix | done — `scripts/evaluate.py`, 10/10 scenarios in docs/evaluation-results.md |

The AI planner is provider-independent and speaks the **OpenAI-compatible**
chat-completions protocol. With `OPENAI_API_KEY` set, plans come
from the configured gateway (`https://vyceai.com/v1` — verified live against
deepseek-v4.1, deepseek-v4-flash, glm-5.3-flash, beam-1.0 and
nemotron-3.5-super-vl; see docs/model-matrix.md); without it, a
deterministic heuristic planner runs and **every artifact is labelled with
the planner identity**, so reports never overstate what produced them.

## Deployment

- **AWS (primary)**: ECS Fargate with autoscaling and self-healing —
  Terraform in `deploy/aws/`, runbook in `docs/aws-deployment.md`
  (includes the ECS-vs-EKS rationale).
- **Local Docker**: `docker compose --env-file .env -f deploy/compose.yaml up --build`
  runs the API, worker, Redis and PostgreSQL together; defaults to in-process
  execution with the file store. See
  [docs/deployment.md](docs/deployment.md#docker-compose-self-contained-local-stack).

Two platforms, one repository:

- **Frontend** — `apps/web` (Next.js) on **Vercel**: import the repo with root
  directory `apps/web`, set `NEXT_PUBLIC_API_URL` to the Render URL.
- **Backend** — the FastAPI service on **Render** (Docker image
  `deploy/Dockerfile.api`, blueprint `render.yaml`): it shells out to `git`
  for shallow clones, which serverless platforms cannot do — hence Render.
- Secrets (`OPENAI_API_KEY`, `GITHUB_TOKEN`, `ALLOWED_ORIGINS`) are set in the
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

RepoMate runs on Linux, macOS, and Windows. The verification sandbox uses
POSIX rlimits on Unix/macOS; on Windows it still enforces the wall-time
budget and environment scrubbing (CPU/memory rlimits are POSIX-only, and the
receipt says so). The Docker images are Linux, so deployments keep the full
sandbox limits. Repository tests run with RepoMate's own interpreter and
installed dependencies; a repo-specific virtualenv is not created.

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
explicit reason — e.g. a repository with no recognized test command.
