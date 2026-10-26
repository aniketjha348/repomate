# Architecture

## Overview

```
                        ┌──────────────────────────────────────────┐
                        │                apps/web                  │
                        │   Next.js workspace (Phase 3, planned)   │
                        └───────────────┬──────────────────────────┘
                                        │ HTTPS + SSE
                        ┌───────────────▼──────────────────────────┐
                        │              services/api                 │
                        │  FastAPI: validation, run lifecycle,      │
                        │  typed errors, SSE progress, artifacts    │
                        └───────────────┬──────────────────────────┘
                                        │  (Phase 5: Celery/Redis queue;
                        │   today: in-process worker thread)
                        ┌───────────────▼──────────────────────────┐
                        │          repomate_core (engine)           │
                        │                                          │
                        │  safety ─► repository ─► evidence         │
                        │     │                        │            │
                        │     │                        ▼            │
                        │     │                    planning ◄─ models
                        │     │                        │       (Ollama
                        │     ▼                        ▼       adapter)
                        │  artifacts ──────────► verification      │
                        │     └──────────► orchestration ◄─────────┘
                        └───────────────┬──────────────────────────┘
                                        │
                       ┌────────────────▼─────────────────┐
                       │  RunStore (files today →          │
                       │  PostgreSQL in Phase 5)           │
                       └───────────────────────────────────┘
```

## The pipeline

`repomate_core.orchestration.pipeline.run_pipeline` executes seven stages,
emitting `RunEvent`s (persisted to `events.jsonl`, replayed over SSE):

1. **VALIDATE_INPUT** — URL policy enforcement (`safety.url_guard`).
2. **PIN_SNAPSHOT** — shallow clone; the run is bound to `commit_sha`
   before any analysis. License, languages, README, entry points are
   recorded (`repository.inspect`).
3. **RETRIEVE_EVIDENCE** — issue fetch (bounded rate-limit handling) and
   keyword-driven retrieval of files/lines (`evidence.collector`) under hard
   file/byte/result/wall-clock budgets. A limit hit ends the run as `PARTIAL`
   with a report of the work left unexamined; it never claims full analysis.
   For model planners, a second bounded loop (`evidence.tools`) exposes typed
   `search_text`/`read_file`/`inspect_manifest` tools; every returned file item
   is re-read from the pinned workspace and re-validated
   (`evidence.validation`) before it can become evidence. A global tool cap
   hit also ends `PARTIAL`.
4. **PLAN** — `ModelPlanner` (Ollama Cloud) or `HeuristicPlanner`
   (deterministic fallback, tests). No evidence ⇒ `NEED_MORE_INFO`;
   unsupported or underspecified tasks are deferred with questions, not
   forced. `BUG_FIX`/`TEST`/`FEATURE`/`REFACTOR` plans may carry anchored
   edits. Model calls and tool-loop research share one per-run call/token
   budget (`models.base.ModelBudget`).
5. **GENERATE_ARTIFACT** — a documentation diff, or an anchored code/test
   patch (`PATCH_DIFF`/`TEST_DIFF`). The workspace is reset afterwards so the
   patch text is the only lasting mutation. A plan with no executable edits
   raises typed `UNSUPPORTED_INPUT` rather than inventing a diff.
6. **VERIFY** — real checks with captured exit codes. The selected
   repository check runs in a clean baseline checkout and a separate patched
   checkout at the same pinned commit, and the receipt records the
   deterministic comparison. Anything not executed is `NOT_RUN` with a reason
   (`verification.runner`).
7. **PUBLISH** — run record, patch, receipt and plan/checklist documents
   persisted; workspace cleaned up unless `REPOMATE_KEEP_WORKSPACE=1`.

Between every stage the pipeline checks a cooperative cancellation marker
and a wall-clock budget (`REPOMATE_MAX_RUN_SECONDS`).

## Agentic RAG without the frameworks

RepoMate's loop *is* agentic RAG, deliberately without LangChain or
LangGraph:

```
retrieve evidence ──► plan ──► act (anchored edits / drafted content)
        ▲                          │
        └── retrieval widens ◄─────┘   (path-token matching, NEED_MORE_INFO)
                                       act is verified ──► honest receipt
```

The reasoning for staying framework-free:

- the whole control flow is ~150 lines of typed Python
  (`orchestration/pipeline.py` + `stages.py`) — a graph framework would
  add a dependency and an abstraction layer to code that already reads
  linearly;
- every state transition is a persisted `RunEvent` and a Pydantic model,
  which is what replayability and the SSE frontend actually need;
- model access is one protocol (`ModelProvider`) with retries, JSON
  mode and corrective re-parsing — the parts agent frameworks sell, at
  ~200 lines we fully control and test (131+ tests);
- retrieval is keyword + path-token scoring over a pinned snapshot:
  deterministic, citable, and debuggable — swapping in embeddings later
  is a change inside `evidence/collector.py`, not an architecture
  change.
- the optional model research loop is bounded by typed tools and hard
  call/byte/time caps; retrieved items pass the same deterministic path,
  line-range and snippet validation as static evidence, so "the model asked
  for it" never upgrades untrusted text into a citation.

If multi-step autonomous iteration (search → edit → run tests → self-
correct across many turns) becomes a requirement, a graph runtime starts
paying for itself; until then it would be ceremony, not capability.

## Provider access

`models.base.ModelProvider` is a small protocol (one `complete`
method). `OpenAIProvider` (in `models/openai.py`) speaks Ollama Cloud’s
standard OpenAI `/chat/completions` dialect; configuration is
environment-driven (`OLLAMA_BASE_URL`, `OLLAMA_MODELS`, `OLLAMA_API_KEY`).
`FallbackProvider` attempts the configured models in order and sticks with
the first model that succeeds for the remainder of the run.

When no key is configured the `HeuristicPlanner` runs and every artifact
carries `planned_by: heuristic-v1`, surfaced in the API and receipts.

## Execution model, today and later

| Concern | Today (Phase 1–2) | Target (Phase 4–5) |
|---|---|---|
| Run execution | in-process worker thread (default) or Celery via Redis () | Celery workers via Redis |
| System of record | JSON files under `var/runs/` | PostgreSQL |
| Check execution | `git apply --check` + policy checks only | disposable sandbox (CPU/RAM/disk/time-limited) with real test suites |
| Cancellation | cooperative marker (file or DB row, seen cross-process) | task revocation + sandbox kill |
| Artifacts | local disk | object storage |

The seams (`RunStore`, `PipelineConfig`, `VerificationCheck`) were chosen so
each row is a drop-in replacement rather than a rewrite.

## Frontend (Phase 3, planned)

Next.js App Router workspace: task submission form, repository map,
evidence browser, plan view, diff viewer, verification panel. Live progress
arrives over SSE; because run state is persisted server-side, a browser
refresh resumes the same run page.
