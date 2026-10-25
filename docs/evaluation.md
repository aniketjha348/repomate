# PS04 Evaluation Plan

## Success criteria (from product-requirements.md)

1. A judge can start a run from a public issue URL.
2. Repository metadata and relevant source locations are verifiable.
3. A contribution plan and at least one reviewable artifact are produced.
4. Available checks execute and show real results; otherwise an explicit
   `NOT_RUN` reason.
5. The model's role and analysis limitations are explained.
6. Artifacts are downloadable from the browser.
7. Malformed input, model failure, GitHub throttling and unsupported tasks
   yield controlled errors.
8. Sandbox and secret-handling tests pass.

## Task matrix

Each row is one recorded run; the harness is `scripts/run_task.py`
(API/web once Phase 3 lands).

| # | Input | Expected outcome |
|---|---|---|
| 1 | Documentation issue on a licensed public repo | `COMPLETED`, docs diff, receipt `PASSED` (patch-level) with test-suite `NOT_RUN` |
| 2 | Repo URL + docs task | same as (1) — proves the task mode |
| 3 | Repo URL + small bug task | `NEED_MORE_INFO` (bug artifacts gated behind slice hardening) — honest deferral |
| 4 | Repo URL + test task | `NEED_MORE_INFO`, same reasoning |
| 5 | Ambiguous task ("make it better") | `NEED_MORE_INFO` with explicit questions |
| 6 | Unsupported toolchain task | typed `UNSUPPORTED_INPUT`-family error |
| 7 | Malformed URL (`http://`, other hosts, PR URLs) | `INVALID_INPUT`, HTTP 400 |
| 8 | Nonexistent repository | `NETWORK_ERROR` |
| 9 | Rate-limit window exhausted | `RATE_LIMITED` (typed, not a crash) |
| 10 | Model gateway failure / timeout | `MODEL_ERROR` |

Current state: rows 1–3 and 5–8 are covered by automated tests
(`tests/integration`, `tests/unit`); rows 1–2 additionally by the opt-in
live e2e (`pytest -m network`). Rows 4, 9, 10 gain purpose-built harnesses
as the slice hardens.

## Honesty scoring

A run is scored invalid (regardless of artifact quality) if:

- a `PASSED`/`FAILED` appears that no real execution or deterministic
  evaluation produced;
- the planner identity is misreported (heuristic output presented as model
  output, or vice versa);
- evidence citations point at paths/lines absent from the pinned snapshot;
- license status is omitted for a repository without a recognized license.
