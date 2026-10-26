# Deployment

RepoMate ships as two deployable surfaces from the single `aniketjha348/repomate`
repository: a Next.js frontend on Vercel and the FastAPI API on Render. This
runbook deploys both and verifies them honestly.

## Architecture: why two platforms

| Surface | Platform | What runs there |
|---|---|---|
| Frontend (`apps/web`) | Vercel | The Next.js app (static/SSR). Talks to the API via `NEXT_PUBLIC_API_URL`. |
| API (`services/api`) | Render (Docker) | FastAPI + the RepoMate pipeline (clone → evidence → plan → artifact → receipt). |

The split is not cosmetic. The API **shells out to `git`** to make shallow
clones of target repositories and writes run records and artifacts to disk.
Serverless platforms such as Vercel Functions cannot do either reliably (no
`git` binary, ephemeral read-only filesystems) — which is exactly why the
backend runs as a long-lived Docker web service on Render.

## Docker Compose (self-contained local stack)

`deploy/compose.yaml` runs the API, a Celery worker, Redis and PostgreSQL on
one machine — useful for dogfooding the durable-execution topology or
verifying the Docker images before deploying.

```bash
cp .env.example .env                 # optional: model key, GitHub token
docker compose --env-file .env -f deploy/compose.yaml up --build
curl http://localhost:8000/api/health
```

Compose looks for `.env` next to the compose file by default, which is why the
repo-root `.env` needs the explicit `--env-file` flag. Without it, Compose uses
your shell environment plus the defaults below and the stack still starts.

On Windows, use Docker Desktop with **Linux containers** and run the same
`docker compose` commands from PowerShell; WSL is not required for the container
path. That path was verified on Docker Desktop for Windows (see below).

| Variable | Default | Effect |
|---|---|---|
| `REPOMATE_EXECUTION` | `inproc` | Runs execute inside the API container; the worker and Redis stay up but idle. |
| `REPOMATE_DATABASE_URL` | empty | Run records use the file-backed store on the `repomate-runs` volume. |
| `POSTGRES_PASSWORD` | `repomate-dev` | Local-only password for the bundled Postgres; override it before exposing the stack. |
| `REPOMATE_SKIP_DOTENV` | empty | Set to `1` to ignore `.env` entirely (the hermetic test suite and the evaluation harness set this). |
| `REPOMATE_RECONCILE_STALE_RUNS` | `1` | At startup, mark runs left `RUNNING`/`PENDING` by a previous process as `FAILED` with an explicit reason, so a restarted server never reports a run that can no longer move. Set to `0` to leave them alone. |
| `OPENAI_MAX_RETRIES` | `2` | Retry budget for retryable gateway failures (429/5xx/524), capped at 6. |
| `REPOMATE_PLANNER_SNIPPET_CHARS` | `600` | Per-evidence snippet budget in the planner prompt (200–4000). Lower it if a gateway times out on large prompts. |
| `REPOMATE_PLANNER_MAX_EVIDENCE` | `6` | Evidence records included in the planner prompt (1–12). |
| `REPOMATE_SANDBOX_ENABLED` | `1` | Execute repository test suites inside the sandbox. Set to `0` to report the suite as `NOT_RUN` instead. |
| `REPOMATE_SANDBOX_NETWORK` | `disabled` | Sandbox egress policy. `disabled` denies the network at the OS layer and verifies the boundary with a live probe; if no enforcing backend exists (`bwrap` on Linux with unprivileged user namespaces) the sandbox **refuses to execute** rather than running with network access. `host` permits egress, is recorded in the receipt as `policy_enforced: false`, and must not be used for public multi-tenant deployments. Any other value is treated as `disabled`. |
| `REPOMATE_RATE_LIMIT_REQUESTS` | `20` | Per-client run submissions allowed in one sliding window. |
| `REPOMATE_RATE_LIMIT_WINDOW_SECONDS` | `60` | Window length for the per-client submission limit. |
| `REPOMATE_MAX_CONCURRENT_RUNS` | `3` | Maximum `PENDING`+`RUNNING` runs; also the worker concurrency default. |
| `REPOMATE_TRUSTED_PROXIES` | empty | IPs/CIDRs whose `X-Forwarded-For` is trusted. Leave empty unless the API is behind a proxy you control. |
| `REPOMATE_MODEL_MAX_CALLS` | `10` | Per-run model call cap, shared by planning and tool research. |
| `REPOMATE_MODEL_MAX_TOKENS` | `120000` | Per-run prompt+completion token cap. |
| `REPOMATE_TOOL_MAX_CALLS` | `8` | Model-directed tool calls per run (one model call each, within the per-run model-call budget). |
| `REPOMATE_TOOL_MAX_TOTAL_BYTES` | `4000000` | Cumulative bytes the tool loop may read. |
| `REPOMATE_TOOL_MAX_SECONDS` | `180` | Wall-clock budget for the model tool loop (live reasoning models regularly need more than 20s). |
| `REPOMATE_TOOL_MAX_RESULTS` | `20` | Maximum matches returned by one `search_text` call. |

Celery applies `REPOMATE_MAX_RUN_SECONDS` as the task soft time limit and a
hard limit 30 s (or 10%, whichever is larger) above it. A soft limit raised
inside the pipeline finalises the record as `FAILED`/`TIMEOUT`; it never leaves
the run `RUNNING`. `REPOMATE_WORKER_CONCURRENCY` explicitly overrides the
worker process count; otherwise it derives from `REPOMATE_MAX_CONCURRENT_RUNS`.
Keep the API and worker environments aligned, because each process reads these
budgets from its own environment.

Fair-use admission has one honest deployment caveat: the per-client sliding
window and the short reservations are per API process. The persisted active-run
count is shared, but multiple replicas can still admit simultaneously and each
keeps its own request window. Run a single API replica, or add a shared limiter
(Redis) before scaling out under hostile traffic.

The API and worker images install `bubblewrap` and copy
`scripts/verify_egress.py` into `/app/scripts/`. Docker's default seccomp
profile blocks the namespace syscalls `bwrap` needs for a non-root process,
so `deploy/compose.yaml` runs both services with
`deploy/seccomp-bwrap.json` (Docker's default profile plus
`clone`/`clone3`/`mount`/`pivot_root`/`setns`/`umount2`/`unshare` and
`sethostname`/`setdomainname` for the private UTS namespace; kernel
capability checks still apply). Without that profile the sandbox fails
closed: repository tests are `NOT_RUN`, never run with network access.

```bash
# Prove the boundary in the actual runtime before exposing it:
docker compose -f deploy/compose.yaml exec api python scripts/verify_egress.py
```

`scripts/verify_egress.py` exits `0` only when the live probe passed and the
receipt says `network_mode: disabled`, `backend: bwrap`,
`policy_enforced: true`, `egress_validation: PASSED`.

This was verified on Docker Desktop for Windows (Linux containers) on
2026-10-26. Both the API and worker gates exited `0`; the same container
reached `1.1.1.1:80` without `bwrap`; the default Docker seccomp profile
failed closed; 32 adversarial tests passed inside the image; and a real issue
run completed with 366 tests executed under `bwrap` in both the baseline and
patched checkouts. Raw evidence:
[`evaluation-runs/container_docker_windows/`](evaluation-runs/container_docker_windows/summary.md).

To exercise the Celery + PostgreSQL path (the production topology), set these
in `.env` and restart the stack:

```dotenv
REPOMATE_EXECUTION=celery
REPOMATE_DATABASE_URL=postgresql://repomate:repomate-dev@postgres:5432/repomate
```

API and worker mount the same `repomate-runs` volume, so file-store runs are
visible from both containers. `docker compose ... down` keeps the named volumes
(`repomate-runs`, `repomate-db`); `down -v` deletes them. Compose waits for the
Redis and PostgreSQL healthchecks before starting the API and worker.

## Backend on Render

1. Push the repository to GitHub. The blueprint at `render.yaml` (repo root)
   describes the whole backend: one web service `repomate-api`, Docker runtime,
   image built from `deploy/Dockerfile.api`, health check `GET /api/health`,
   free plan, auto-deploy on push.
2. Render Dashboard → **New → Blueprint** → select the repo → **Apply/Confirm**.
3. Set the secret environment variables when prompted, or later under the
   service's **Environment** tab (the blueprint deliberately does not carry
   them — `sync: false`):
   - `OLLAMA_API_KEY` — **optional**. Without it the deterministic heuristic
     planner runs and **every artifact is labelled with the planner identity**,
     so reports never overstate what produced them.
   - `GITHUB_TOKEN` — **recommended**. Render's egress IPs are shared and share
     GitHub's 60 req/h unauthenticated REST budget; a classic personal access
     token with no scopes (sufficient for public repos) lifts this.
   - `ALLOWED_ORIGINS` — comma-separated CORS origins for the API. Set it to
     your Vercel frontend URL, e.g. `https://repomate.vercel.app`. If you
     don't know the URL yet (chicken-and-egg), finish the Vercel deploy below
     first, then set it here — changing an env var restarts the service, no
     rebuild needed.
4. Note the service URL: `https://<service-name>.onrender.com`.

Free-tier honesty: the free plan spins the service down after ~15 minutes of
inactivity. The first request after a spin-down pays a cold start — often tens
of seconds, sometimes longer for Docker images — so a "slow" `/api/health`
right after a pause is expected, not a bug. Render's free hours (750/month)
are otherwise ample for a demo.

### Security gate before public exposure

Do **not** enable a public service that executes arbitrary repository tests
until the runtime's network boundary has been proven in that runtime. Render's
Docker runtime does not expose Docker's `security_opt`/custom seccomp setting,
so `bwrap` may be unable to create namespaces there; in that case the sandbox
fails closed and every repository suite is `NOT_RUN`. That is the safe
behaviour, not a reason to set `REPOMATE_SANDBOX_NETWORK=host`. If a public
deployment needs to execute tests, run it on a runtime that supports the
custom seccomp profile (the Compose/AWS container path) and run:

```bash
python scripts/verify_egress.py     # must exit 0
```

The adversarial acceptance suite (`tests/unit/test_egress_isolation.py`,
`tests/integration/test_egress_isolation_pipeline.py`) must also run on that
Linux host. It exercises the real sandbox boundary, not a mocked policy.
The recorded run for this repository is
[egress-verification.md](egress-verification.md).

## Frontend on Vercel

1. Vercel Dashboard → **Add New… → Project** → import `aniketjha348/repomate`.
2. Configure the import:
   - **Root Directory:** `apps/web`
   - **Framework Preset:** Next.js (auto-detected from `apps/web`)
   - **Environment Variable:** `NEXT_PUBLIC_API_URL` =
     `https://<render-service>.onrender.com` (the Render URL from above)
3. **Deploy**.
4. Copy the production URL Vercel assigns (e.g. `https://repomate.vercel.app`)
   into Render's `ALLOWED_ORIGINS` if you deferred step 3 above.

Cost honesty: the $50 Vercel credit covers Hobby+ usage comfortably for a
demo — this app is a small SSR surface with no meaningful traffic.

## CI and deployment automation (GitHub Actions)

The dashboard clicks above are the one-time provisioning. After that,
`.github/workflows/` does the shipping:

| Workflow | Runs | What it does |
|---|---|---|
| `ci.yml` | every push to `main` and every PR | backend suite (`pytest tests/unit tests/integration`), the sandbox egress boundary, and `npm ci && next build` for `apps/web`. |
| `deploy-render.yml` | push to `main` touching backend paths, or **Run workflow** | CI gate → `POST` the Render deploy hook → poll `/api/health`. |
| `deploy-vercel.yml` | push to `main` touching `apps/web`, or **Run workflow** | CI gate → `vercel build --prod` → `vercel deploy --prod --prebuilt`. |

Both deploy workflows `uses: ./.github/workflows/ci.yml`, so nothing reaches
production unless CI is green. They also fail closed on missing configuration
rather than deploying a silently mis-wired build.

### One-time GitHub configuration

GitHub → repository → **Settings → Secrets and variables → Actions**.

Secrets:

| Name | Where it comes from |
|---|---|
| `RENDER_DEPLOY_HOOK` | Render → `repomate-api` → Settings → **Deploy Hooks** (copy the URL). |
| `VERCEL_TOKEN` | Vercel → Account Settings → Integrations → API Tokens (a CI-scoped token). |
| `VERCEL_ORG_ID` | Vercel → Project → Settings → General → Team ID. |
| `VERCEL_PROJECT_ID` | Vercel → Project → Settings → General → Project ID. |

Do **not** add `OLLAMA_API_KEY` or `GITHUB_TOKEN` here. Those belong to the
runtime that serves traffic (Render's environment, per `render.yaml`), not to
CI; keeping them out of GitHub means no workflow run can see or echo them, and
the test suite is written to run with them cleared.

Variables (non-secret, they end up in the client bundle or a log line):

| Name | Value |
|---|---|
| `NEXT_PUBLIC_API_URL` | `https://<render-service>.onrender.com` |
| `RENDER_SERVICE_URL` | the same Render origin, enables the post-deploy health gate |

`NEXT_PUBLIC_API_URL` is baked in at build time. If the Render URL changes,
re-run **Deploy frontend (Vercel)** — a rebuild, not a restart.

### What CI does not cover

CI is a real gate, not a substitute for the security gate above it:

- The egress job installs `bubblewrap` and probes namespace creation first. On
  a runner that cannot create user namespaces it skips the live probe and runs
  the fail-closed tests instead, and prints a notice — the boundary is still
  only proven for the runtime that actually serves traffic, so
  `python scripts/verify_egress.py` must be run there before making the API
  public.
- Deployments target named GitHub environments (`render-production`,
  `vercel-production`). Add protection rules there — required reviewers or a
  branch constraint — if you want a human in the loop before `main` ships.
- A green pipeline is not an all-clear for exposure. The API still has no
  authentication, so `GET /api/runs`, run cancellation and artifact downloads
  are open to anyone who can reach the origin; CI cannot test a control that
  does not exist. Treat the Render URL as a demo origin until the access-control
  work lands.

## Post-deploy verification

1. `curl https://<render-service>.onrender.com/api/health` — expect
   `{"status": "ok", ..., "planner": "..."}`. The `planner` field is the
   planner identity (e.g. `heuristic-v1` without an `OLLAMA_API_KEY`, the
   model-backed planner with one); the same identity is stamped into every
   artifact.
2. Open the Vercel URL and submit a public issue URL, for example:
   - `https://github.com/astanin/python-tabulate/issues/481`
   For a repository-plus-task run, use the API (`POST /api/runs` with
   `repo_url` and `task`); the web form accepts issue URLs.
3. Watch the SSE event stream on the run page (clone → evidence → plan →
   artifact → receipt).
4. Download the patch and `CONTRIBUTION_PLAN.md` from the run page
   (`GET /api/runs/{id}/artifacts` lists both) and confirm the patch is a real,
   applicable diff.

## Troubleshooting

| Symptom | Cause / fix |
|---|---|
| Browser console shows CORS errors | `ALLOWED_ORIGINS` on Render must **exactly** match the Vercel origin — including `https://`, correct subdomain, and no trailing slash (`https://x.vercel.app` ≠ `https://x.vercel.app/`). Fix it in the Render Environment tab; the service restarts itself. |
| GitHub API returns 403 rate-limit errors | Set `GITHUB_TOKEN` on Render. Shared Render egress IPs share the 60 req/h unauthenticated REST budget. |
| First request hangs for ~30 s or more | Render free-tier cold start after spin-down. Wait it out and retry. Don't add keep-alive pingers — they burn the free hours. |
| Plans look deterministic / `planner` is `heuristic-v1` | Either no model is configured (fine — artifacts are labelled honestly) or the provider call failed. Check `model_configured` and `env_file` in `/api/health`: an empty `env_file` means no `.env` was found, so set `OLLAMA_API_KEY` in the environment or place `.env` at the repo root. Then check the Render logs. |
| Run stuck on `RUNNING` after a restart | In-process execution cannot resume a run whose process died. Startup reconciliation marks it `FAILED` with a reason (see `REPOMATE_RECONCILE_STALE_RUNS`); re-submit the task. |
| `MODEL_ERROR` with `status 524` | Cloudflare’s origin timeout: the provider is still working but its edge gave up. Raise `OLLAMA_MAX_RETRIES`, or lower `REPOMATE_PLANNER_SNIPPET_CHARS` / `REPOMATE_PLANNER_MAX_EVIDENCE` to shrink the prompt. |
| `repository-test-suite` is `NOT_RUN` with "no enforcing backend" | The host has no egress-enforcement mechanism (needs `bwrap` on Linux with unprivileged user namespaces). The sandbox refuses to run untrusted code with network access rather than downgrading the control. Install `bubblewrap` and run with a seccomp profile that permits namespaces, or set `REPOMATE_SANDBOX_NETWORK=host` only for a trusted local environment (never public). |
| `repository-test-suite` is `NOT_RUN` with "egress isolation could not be verified" | The backend is present but the probe reached the network from inside the sandbox. Treat as a security failure: the namespace is not taking effect. Check the container's seccomp/AppArmor policy and whether the runtime blocks unprivileged user namespaces. |
| `sandbox-egress-isolation` is `FAILED` | A live connection attempt from inside the sandbox succeeded. The receipt names the reachable target. Do not serve public traffic until it passes. |
| Repository tests fail on a missing import | The check should be `NOT_RUN` with the missing module named: the sandbox has no network, so dependencies cannot be downloaded. Pre-bake common dependencies into the image; never set `REPOMATE_SANDBOX_NETWORK=host` to make the import disappear. |

**Provider note (honesty):** Ollama Cloud (`https://ollama.com/v1`) is the
configured provider; `OLLAMA_BASE_URL`, `OLLAMA_API_KEY`, and a comma-separated
`OLLAMA_MODELS` chain are environment-driven. If every model in the chain
rejects a call, the run fails with a typed `MODEL_ERROR` and the reason in the
logs — the heuristic fallback only applies when no key is configured at all, so
a report never claims a model produced a plan that it did not.

## Local development

Backend (repo root):

```bash
pip install -e ".[api]"
uvicorn services.api.main:app --reload    # http://localhost:8000
```

Frontend (`apps/web`):

```bash
npm install
NEXT_PUBLIC_API_URL=http://localhost:8000 npm run dev    # http://localhost:3000
```

`.env.example` (repo root, backend: `ALLOWED_ORIGINS=http://localhost:3000`
etc.) and `apps/web/.env.local.example` (frontend: `NEXT_PUBLIC_API_URL`)
carry these values for local use.
