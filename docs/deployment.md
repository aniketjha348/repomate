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

## Backend on Render

1. Push the repository to GitHub. The blueprint at `render.yaml` (repo root)
   describes the whole backend: one web service `repomate-api`, Docker runtime,
   image built from `deploy/Dockerfile.api`, health check `GET /api/health`,
   free plan, auto-deploy on push.
2. Render Dashboard → **New → Blueprint** → select the repo → **Apply/Confirm**.
3. Set the secret environment variables when prompted, or later under the
   service's **Environment** tab (the blueprint deliberately does not carry
   them — `sync: false`):
   - `VYCE_API_KEY` — **optional**. Without it the deterministic heuristic
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

## Post-deploy verification

1. `curl https://<render-service>.onrender.com/api/health` — expect
   `{"status": "ok", ..., "planner": "..."}`. The `planner` field is the
   planner identity (e.g. `heuristic-v1` without a `VYCE_API_KEY`, the
   model-backed planner with one); the same identity is stamped into every
   artifact.
2. Open the Vercel URL and submit a small docs task:
   - Repository: `https://github.com/psf/black`
   - Task: `Add documentation for the exclude option to the README`
3. Watch the SSE event stream on the run page (clone → evidence → plan →
   artifact → receipt).
4. Download the patch from the run page (`GET /api/runs/{id}/artifacts/patch`)
   and confirm it is a real, applicable diff.

## Troubleshooting

| Symptom | Cause / fix |
|---|---|
| Browser console shows CORS errors | `ALLOWED_ORIGINS` on Render must **exactly** match the Vercel origin — including `https://`, correct subdomain, and no trailing slash (`https://x.vercel.app` ≠ `https://x.vercel.app/`). Fix it in the Render Environment tab; the service restarts itself. |
| GitHub API returns 403 rate-limit errors | Set `GITHUB_TOKEN` on Render. Shared Render egress IPs share the 60 req/h unauthenticated REST budget. |
| First request hangs for ~30 s or more | Render free-tier cold start after spin-down. Wait it out and retry. Don't add keep-alive pingers — they burn the free hours. |
| Plans look deterministic / `planner` is `heuristic-v1` | Either `VYCE_API_KEY` is unset (fine — artifacts are labelled honestly) or the gateway call failed; check `model_configured` in `/api/health` and the Render logs. |

**Vyce gateway note (honesty):** the Vyce AI gateway endpoint and model IDs
(`VYCE_BASE_URL`, `VYCE_MODEL`) are env-driven and were never verified against
a live key. If the gateway rejects them at runtime, the pipeline falls back to
the heuristic planner (`heuristic-v1`) and says so in every artifact — it will
not pretend a model produced the plan.

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
