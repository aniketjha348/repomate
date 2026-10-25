# PS04 Evaluation Results

Generated 2026-10-25T18:58:34.555434+00:00 by `scripts/evaluate.py` (deterministic, hermetic; rate-limit and model failures are simulated injections).

| # | Scenario | Expected | Actual outcome | Pass |
|---|----------|----------|----------------|------|
| 1 | Documentation task (fixture) | COMPLETED, docs diff, patch checks PASSED, fixture suite PASSED | `status=COMPLETED · overall=PASSED · suite=PASSED · planner=heuristic-v1 · paths=readme.md` | ✅ |
| 3 | Small bug task | NEED_MORE_INFO (bug artifacts gated behind slice hardening) | `status=NEED_MORE_INFO · questions=yes` | ✅ |
| 4 | Test task | NEED_MORE_INFO (test artifacts deferred) | `status=NEED_MORE_INFO · questions=yes` | ✅ |
| 5 | Ambiguous task | NEED_MORE_INFO with explicit questions | `status=NEED_MORE_INFO · questions=yes` | ✅ |
| 6 | Unsupported toolchain | suite NOT_RUN with reason (no supported toolchain) | `status=COMPLETED · overall=PASSED · suite=NOT_RUN · planner=heuristic-v1 · paths=readme.md` | ✅ |
| 6b | Failing repository suite | COMPLETED with honest FAILED suite check | `status=COMPLETED · overall=FAILED · suite=FAILED · planner=heuristic-v1 · paths=readme.md` | ✅ |
| 7 | Malformed URLs | typed INVALID_INPUT for every malformed URL | `errors=INVALID_INPUT,INVALID_INPUT,INVALID_INPUT,INVALID_INPUT` | ✅ |
| 8 | Nonexistent repository | typed NETWORK_ERROR | `status=FAILED · error=NETWORK_ERROR` | ✅ |
| 9 | GitHub rate limit (simulated) | typed RATE_LIMITED (simulated) | `status=FAILED · error=RATE_LIMITED` | ✅ |
| 10 | Model gateway failure (simulated) | typed MODEL_ERROR (simulated gateway failure) | `status=FAILED · error=MODEL_ERROR` | ✅ |

Rows 1–2 of docs/evaluation.md (live GitHub runs) are covered by the opt-in
network e2e test (`pytest -m network tests/e2e/test_live_github.py`) and the
browser walkthrough recorded in the repository history.
