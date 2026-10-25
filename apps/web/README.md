# apps/web — RepoMate workspace

The browser workspace for RepoMate: task submission form plus a live run page
with repository snapshot, evidence browser, contribution plan, unified diff
viewer and verification panel. Built with Next.js (App Router) + TypeScript
(strict) + Tailwind CSS v4, talking to the FastAPI backend over
`POST /api/runs`, `GET /api/runs/{id}` and SSE on `GET /api/runs/{id}/events`.

## Setup

```bash
cd apps/web
npm install
```

Copy the example env file and adjust if your backend runs elsewhere:

```bash
cp .env.local.example .env.local
```

| Variable             | Default                  | Purpose                          |
| -------------------- | ------------------------ | -------------------------------- |
| `NEXT_PUBLIC_API_URL` | `http://localhost:8000` | Base URL of the FastAPI backend. |

`NEXT_PUBLIC_` variables are inlined at build time — set them before running
`npm run build`.

## Development

```bash
npm run dev        # http://localhost:3000
```

The backend is expected at `NEXT_PUBLIC_API_URL` (default
`http://localhost:8000`) with CORS enabled for `http://localhost:3000`.

## Production build

```bash
npm run build      # type-checks and builds; must pass with zero TS errors
npm run start      # serve the production build
```

## Deploying to Vercel

1. Import the repository and set **Root Directory** to `apps/web`.
2. Add the environment variable `NEXT_PUBLIC_API_URL` pointing at the deployed
   backend (for example the Render service URL, `https://repomate-api.onrender.com`).
3. Deploy — the API is called browser-side, so the backend must allow CORS
   from the Vercel origin.

## Structure

- `app/` — routes: landing (submission), `runs/[runId]` workspace, 404.
- `components/ui/` — hand-rolled shadcn-compatible primitives (no Radix).
- `components/repository-input/` — submission forms.
- `components/run/` — run workspace panels (snapshot, evidence, plan, diff,
  verification, events feed).
- `lib/` — API client, SSE subscription, types mirroring backend JSON,
  single-pass unified-diff parser, config and utilities.
