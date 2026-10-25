# Product Requirements

## Problem background (PS04)

New contributors often struggle to understand an unfamiliar repository,
connect an issue to relevant files, and determine which tests to run.
Maintainers also face repetitive questions and low-quality proposed
fixes that are difficult to review. An evidence-backed assistant can
reduce this friction without claiming that automated code suggestions
have already been verified.

RepoMate addresses each half of that background explicitly:

- **Understanding an unfamiliar repository** — every run carries a
  snapshot-derived *repository orientation* (summary, key paths with
  reasons, languages, entry points), all traceable to the pinned commit.
- **Connecting an issue to relevant files** — the evidence browser cites
  paths, line ranges and snippets with per-record rationale.
- **Determining which tests to run** — *test guidance* lists the
  evidence-matched test files, a focused command to start with, and the
  authoritative full-suite command (which the verification stage actually
  executed).
- **Reviewable, honest suggestions** — patches are anchored to verbatim
  snapshot text, verified against the pinned commit, and executed in the
  sandbox; planner identity and every NOT_RUN reason are disclosed.

## Product

RepoMate is an evidence-first open-source contribution agent. A developer
provides a public GitHub issue URL, or a repository URL plus a development
task. RepoMate:

1. **Understands the repository** — languages, README, entry points,
   license, contributor instructions.
2. **Analyzes evidence-first** — relevant source paths, lines, snippets,
   mapped to the issue.
3. **Produces contribution artifacts** — patch, docs diff, test, or
   reproduction checklist.
4. **Reports real verification** — actual test results, failure reasons,
   and honest limitations.

## Non-goals (MVP)

- automatic issue discovery
- submitting PRs to GitHub
- multi-agent orchestration

These are excluded so the core contribution workflow can be solved
end-to-end first; each is a candidate for a later phase only after the
workflow is reliable.

## Hard product rules

- Every run is pinned to an exact repository commit.
- Evidence-first: if evidence is insufficient, retrieve more or return
  `NEED_MORE_INFO`. **Never force a code change without evidence.**
- Verification statuses (`PASSED`/`FAILED`/`NOT_RUN`) derive only from real
  execution or deterministic evaluation; `NOT_RUN` always carries a reason.
- The planner identity (model vs heuristic) is recorded on every plan and
  artifact and surfaced to the user.
- Model-proposed edits are exact-anchor search/replace: `old_text` must
  match the pinned snapshot verbatim and uniquely, or the run fails with a
  typed `MODEL_ERROR` — never a silently partial patch.
- The test suite executes against the **patched** tree, so a fix's effect
  on the suite is actually measured.
- License status is displayed explicitly for every run.
- Malformed input, model failure, GitHub throttling and unsupported tasks
  produce controlled, typed errors.

## Workflow (the product's spine)

validate input → pin repository snapshot → retrieve evidence →
plan the contribution → generate + validate artifact → execute checks →
publish the report

## Web experience (Phase 3)

A single workspace: task submission form → run page with repository map,
evidence browser, reviewable diff, check results. SSE for live progress;
run state persists server-side so refresh/disconnect resumes the same run.

## Enterprise safeguards (required from the start, not retrofitted)

- URL and network safety: validated public GitHub URLs only; redirect and
  destination-IP validation (SSRF).
- Repository execution isolation: untrusted test scripts never run on the
  API server; disposable sandbox with resource + time limits (Phase 4).
- Secret management: model keys server-side only; never in frontend or logs.
- Bounded AI runs: step limits, model timeouts, capped retries, budgets,
  cancellation.
- Patch integrity: diffs validated on a clean snapshot; forbidden paths and
  unexpected changes rejected.
- Durable run lifecycle: status, errors, artifacts persisted; stale
  workspaces cleaned up.
- Honest verification (see hard rules).
- Rate-limit handling for GitHub API quota with backoff/throttling.

## Build order

1. Foundation and contracts *(done)*
2. Working Python core + docs vertical slice *(done)*
3. Web experience
4. Safe verification sandbox
5. Production readiness (Celery, PostgreSQL, monitoring, security tests)
6. PS04 evaluation matrix (docs/evaluation.md)

## Completion criteria

The product is complete when a judge can start from a public issue URL and
verify metadata, evidence locations, plan, artifact, actual check results
(or explicit `NOT_RUN`), model-role disclosure, and downloadable artifacts —
with controlled errors for every failure mode and passing sandbox/secret
tests.
