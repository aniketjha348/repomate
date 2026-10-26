# RepoMate

**Evidence-first open-source contribution agent.**

A developer gives RepoMate a public GitHub issue URL (or a repository URL plus a
development task). RepoMate inspects the repository, locates relevant evidence,
builds a contribution plan, produces a suitable artifact (a documentation or
test diff, an evidence-anchored code patch, and the matching plan/checklist
documents), and reports **actual** verification results — with honest
limitations, never fabricated ones.

Evidence-first is enforced, not just labelled. Every citation a plan makes is
validated against that run's evidence records before any artifact is produced:
unknown ids, paths missing from the pinned snapshot, out-of-range line numbers,
a stale commit, and evidence that shares no distinctive vocabulary with the
claim it is attached to all downgrade the claim to a **hypothesis** with a
recorded warning. A claim is only `supported` when every citation it makes
resolves. See `packages/repomate_core/evidence/grounding.py`.

Out of scope for the MVP (deliberately): automatic issue discovery, submitting
PRs to GitHub, multi-agent orchestration. PS04's contribution workflow comes
first; enterprise capabilities exist to make that workflow reliable and secure.

## Status

| Phase | Scope | State |
|---|---|---|
| 1 | Contracts + architecture | done |
| 2 | Working Python core + vertical slice (docs task → real diff → receipt) | done |
| 3 | Web experience (Next.js workspace) | done |
| 4 | Verification sandbox (process backend: denied network egress, wall-time/CPU/memory limits, env scrubbing) | done — WSL `bwrap` and Compose container gates verified, including Docker Desktop for Windows and the default-seccomp fail-closed case |
| 5 | Durable execution: SQL run store (SQLite→PostgreSQL), Celery worker + Redis, metrics, stale-workspace sweeps | done (in-process mode remains the default) |
| 6 | PS04 evaluation matrix | done — 14/14 hermetic scenarios (`docs/evaluation-results.md`) and 12 public-repository cases in `docs/evaluation-real-results.md` (11 passed; the live-model case hit a real gateway 524 and is preserved as a typed `MODEL_ERROR`) |

The AI planner uses **Ollama Cloud** through its OpenAI-compatible
chat-completions API. With `OLLAMA_API_KEY` set, plans come from
`gemma4:31b`, falling back to `gpt-oss:120b` if the first model fails; without
it, a deterministic heuristic planner runs and **every artifact is labelled with
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
- Secrets (`OLLAMA_API_KEY`, `GITHUB_TOKEN`, `ALLOWED_ORIGINS`) are set in the
  Render dashboard; `ALLOWED_ORIGINS` must exactly match the Vercel origin.
- **Shipping** — `.github/workflows/` runs CI (backend suite + sandbox egress
  boundary + `next build`) on every push and PR, and gates the
  `deploy-render.yml` / `deploy-vercel.yml` pipelines that publish each surface.
  Required GitHub secrets and variables are listed in
  [docs/deployment.md](docs/deployment.md#ci-and-deployment-automation-github-actions).

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
budgets. RepoMate reads that file itself at startup (API, worker and the
`scripts/` harnesses), so no `source .env` step is needed — and a variable
already exported in the shell always wins over the file. Set
`REPOMATE_SKIP_DOTENV=1` to ignore `.env` entirely.

`GET /api/health` reports which `.env` the process loaded (`env_file`) and
whether a model is configured, so a heuristic-planner run is never a silent
surprise.

RepoMate runs on Linux, macOS, and Windows. The verification sandbox denies
network egress by default and enforces it at the OS layer, then proves the
boundary with a live probe before untrusted code runs. On Linux that is an
unprivileged `bwrap` namespace: no network, its own PID table, a synthesized
`/proc` and `/dev`, a narrow read-only bind set (host socket directories are
masked, `/etc` is not exposed wholesale), and a read-only `.git` so sandboxed
code cannot poison the host-side reset. If no enforcing backend exists, the
sandbox **refuses to execute** rather than running with network access, and
the check is `NOT_RUN` with the reason. The receipt records the policy under
`sandbox` (`network_mode`, `backend`, `policy_enforced`, `egress_validation`).
POSIX rlimits add CPU/memory/file-size budgets; on Windows only the wall-time
budget and environment scrubbing apply, and no network namespace exists, so
repository commands are refused unless the operator explicitly sets
`REPOMATE_SANDBOX_NETWORK=host`. The Docker images install `bubblewrap` and
the Compose file runs them with `deploy/seccomp-bwrap.json`, because Docker's
default seccomp profile otherwise blocks the namespace syscalls; without that
profile the sandbox fails closed. Verified on Docker Desktop for Windows: both
API and worker gates passed, default seccomp failed closed, 32 adversarial
tests passed in-container, and a real issue run executed 366 tests under
`bwrap` (see
[`docs/evaluation-runs/container_docker_windows/`](docs/evaluation-runs/container_docker_windows/summary.md)).
Repository tests run with RepoMate's own
interpreter and installed dependencies; a missing dependency is
`NOT_RUN` with the module name, never a fabricated pass — dependencies that
would need the network cannot be fetched. The recorded baseline/post run and
the Docker gate are in
[docs/egress-verification.md](docs/egress-verification.md).

## Layout

```
apps/web/            Next.js frontend (App Router + TypeScript; deploys to Vercel)
services/api/        FastAPI app
services/worker/     Celery + sandbox entry point (Phase 4/5)
packages/repomate_core/   the engine: repository, evidence, planning,
                          models, artifacts, verification, safety, orchestration
tests/               unit / integration (hermetic) / e2e (opt-in network)
deploy/              Dockerfiles + compose
docs/                architecture, security, deployment, evaluation, verification, product requirements
```

API and worker share `repomate_core`; no business logic is duplicated per
surface.

## HTTP API (MVP)

| Route | Purpose |
|---|---|
| `POST /api/runs` | start a run (`issue_url`, or `repo_url` + `task`) |
| `GET /api/runs/{id}` | full run record (snapshot, evidence, plan, grounding, receipt) |
| `GET /api/runs/{id}/events` | SSE progress stream |
| `GET /api/runs/{id}/artifacts` | list the primary patch and every markdown document |
| `GET /api/runs/{id}/artifacts/patch` | download the generated patch |
| `GET /api/runs/{id}/artifacts/{name}` | download a document such as `CONTRIBUTION_PLAN.md` |
| `POST /api/runs/{id}/cancel` | cooperative cancellation |
| `GET /api/health` | liveness + active planner identity |
| `GET /api/metrics` | status/planner counts + fair-use admission state |

Run records survive server restarts (file-backed store today; PostgreSQL is
the Phase 5 system of record), so refreshing the browser mid-run loses
nothing.

## Honest verification model

Every run ends with a receipt. `PASSED`/`FAILED` only ever come from checks
that actually executed (e.g. `git apply --check` against the pinned commit, or
a deterministic policy evaluation). Anything not executed is `NOT_RUN` with an
explicit reason — e.g. a repository with no recognized test command.

When a repository check is available, it executes twice: once in a clean
checkout of the pinned commit, and once in a separate checkout with the
validated patch applied. Both runs use the same command, sandbox and scrubbed
environment. The receipt records the base commit, patch SHA-256, exact
commands, exit codes, durations, output summaries and a deterministic
comparison:

| Baseline | Post-patch | Comparison |
| --- | --- | --- |
| `FAILED` | `PASSED` | consistent improvement — not final proof of correctness |
| `PASSED` | `PASSED` | no regression detected in the selected checks |
| `FAILED` | `FAILED` | unresolved |
| `PASSED` | `FAILED` | potential regression |
| `NOT_RUN` | any | baseline incomplete |
| any | `NOT_RUN` | post-patch incomplete |

A successful post-patch check is never labelled a "verified fix". Until the
comparison and issue-specific behavior establish more, the receipt says
"selected checks passed; issue resolution not fully established."

## Bounded retrieval

Repository retrieval is bounded by files examined, bytes per file, cumulative
bytes, matching search results and wall-clock time (defaults: 2,000 files,
200 KB/file, 32 MB total, 200 matches, 30 s; see `.env.example`). Reaching any
limit stops the scan and ends the run as **`PARTIAL`** — never `COMPLETED`.
The run record publishes the evidence and orientation it did gather plus a
`retrieval` report listing every exhausted limit and the files, bytes or
matches that were **not examined**. `PARTIAL` means exactly that: the analysis
does not cover the whole repository. Raising the limits is an operator
decision, not something the model can do mid-run.

Evidence validation verifies citation integrity (the cited evidence exists,
belongs to this run and is not stale), but selection is lexical rather than
semantic. Relevant evidence can be missed and a lexically matching record can
be cited for the wrong reason. The current limitation is documented rather
than hidden; a future evaluation should measure false-positive and
false-negative rates before treating citation support as semantic relevance.

## Bounded model research

When a model planner runs, it may request supplementary context through
exactly three typed, read-only tools: `search_text`, `read_file` and
`inspect_manifest`. The loop is capped per run by tool calls, total bytes and
wall-clock time (`REPOMATE_TOOL_*`; defaults: 8 calls, 4 MB, 180 s, 20 search
results). Model calls made here share the run's call/token budget
(`REPOMATE_MODEL_MAX_CALLS`, `REPOMATE_MODEL_MAX_TOKENS`), so research and
planning cannot spend twice.

The model chooses *where* to look; it never supplies evidence text. Every
retrieved file item is re-read from the pinned workspace, its line range is
checked, and its snippet is rebuilt from the actual file. A fabricated path,
stale commit, out-of-range/empty span or oversized snippet is rejected and
counted; it never enters the evidence set. A global cap hit ends the run as
**`PARTIAL`** with the remaining work, never as a completed analysis. Heuristic
runs skip the loop entirely.

## Evaluation evidence

- `scripts/evaluate.py` runs a 14-scenario hermetic matrix covering every task
  type, document kind, comparison outcome and typed error without network
  access; results are in [`docs/evaluation-results.md`](docs/evaluation-results.md).
- `scripts/evaluate_real_repos.py` runs public repositories through the real
  clone, evidence, artifact, sandbox and verification path. Each case preserves
  its input, upstream/prepared commits, evidence, artifact, receipt and
  comparison under [`docs/evaluation-runs/`](docs/evaluation-runs/), summarized
  in [`docs/evaluation-real-results.md`](docs/evaluation-real-results.md).
- The browser path is demonstrated separately: a real Chrome session submitted
  issue #481, waited for `COMPLETED`, rendered the plan/diff/receipt and
  downloaded the patch and `CONTRIBUTION_PLAN.md`. Screenshot, DOM, run record
  and downloaded files are in
  [`docs/evaluation-runs/browser_tabulate_481/`](docs/evaluation-runs/browser_tabulate_481/).
- The Compose images were verified on Docker Desktop for Windows from Windows
  PowerShell: API and worker egress gates passed, the default-seccomp control
  failed closed, 32 adversarial tests passed inside the image, and a real
  issue run completed with the repository suite executing under `bwrap`.
  Gates, controls, logs, run record and downloads are in
  [`docs/evaluation-runs/container_docker_windows/`](docs/evaluation-runs/container_docker_windows/summary.md).
- The final PS04 requirement-by-requirement audit, with code references and
  explicit `FAIL`/`NOT_VERIFIED` entries, is
  [`docs/acceptance-audit.md`](docs/acceptance-audit.md).

## Fair-use controls

`POST /api/runs` applies a per-client sliding-window rate limit and a global
concurrency cap before creating a run (`429 RATE_LIMITED` with `Retry-After`).
Per-run runtime, model/token and tool budgets are enforced in the pipeline;
cancellation is cooperative; workspaces are removed on terminal paths and
swept at startup. When the API sits behind a proxy, set
`REPOMATE_TRUSTED_PROXIES` to the proxy's IP/CIDR; otherwise `X-Forwarded-For`
is ignored so clients cannot spoof their way around the limit.

The rate window is per API process. Before running multiple API replicas under
hostile traffic, replace the in-process limiter with a shared store (Redis).
`GET /api/metrics` exposes aggregate `fair_use` counters and active/max runs;
it does not expose run identifiers, prompts, environment contents or
filesystem paths.
