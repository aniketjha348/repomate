# PS04 Evaluation Results

Generated 2026-10-26T10:20:58.397648+00:00 by `scripts/evaluate.py` (deterministic, hermetic; rate-limit and model failures are simulated injections).

| # | Scenario | Expected | Actual outcome | Pass |
|---|----------|----------|----------------|------|
| 1 | Documentation task (fixture) | COMPLETED, docs diff, patch checks PASSED, fixture suite PASSED | `status=COMPLETED · overall=PASSED · suite=PASSED · comparison=NO_REGRESSION_DETECTED(PASSED->PASSED) · retrieval=COMPLETE · artifact=DOCS_DIFF · planner=heuristic-v1 · paths=readme.md · documents=CONTRIBUTION_PLAN.md` | ✅ |
| 2 | Bug fix with relevant test | COMPLETED, PATCH_DIFF + CONTRIBUTION_PLAN.md + REPRO_CHECKLIST.md | `status=COMPLETED · overall=PASSED · suite=PASSED · comparison=NO_REGRESSION_DETECTED(PASSED->PASSED) · retrieval=COMPLETE · artifact=PATCH_DIFF · planner=scripted-eval-v1 · paths=src/fixture/core.py · documents=CONTRIBUTION_PLAN.md,REPRO_CHECKLIST.md` | ✅ |
| 3 | Test-addition task | COMPLETED, TEST_DIFF + CONTRIBUTION_PLAN.md | `status=COMPLETED · overall=PASSED · suite=PASSED · comparison=NO_REGRESSION_DETECTED(PASSED->PASSED) · retrieval=COMPLETE · artifact=TEST_DIFF · planner=scripted-eval-v1 · paths=tests/test_timeout_regression.py · documents=CONTRIBUTION_PLAN.md` | ✅ |
| 4 | Ambiguous task | NEED_MORE_INFO with explicit questions + downloadable plan | `status=NEED_MORE_INFO · retrieval=COMPLETE · documents=CONTRIBUTION_PLAN.md · questions=yes` | ✅ |
| 5 | Large repository (retrieval limit) | PARTIAL with remaining retrieval work; no plan or patch | `status=PARTIAL · retrieval=PARTIAL` | ✅ |
| 6 | Missing license | license ABSENT surfaced in run and plan document | `status=COMPLETED · overall=PASSED · suite=PASSED · comparison=NO_REGRESSION_DETECTED(PASSED->PASSED) · retrieval=COMPLETE · artifact=DOCS_DIFF · planner=heuristic-v1 · paths=readme.md · documents=CONTRIBUTION_PLAN.md` | ✅ |
| 7 | Unsupported toolchain | suite NOT_RUN with reason (no supported toolchain) | `status=COMPLETED · overall=PASSED · suite=NOT_RUN · comparison=BASELINE_INCOMPLETE(NOT_RUN->NOT_RUN) · retrieval=COMPLETE · artifact=DOCS_DIFF · planner=heuristic-v1 · paths=readme.md · documents=CONTRIBUTION_PLAN.md` | ✅ |
| 7b | Failing repository suite | COMPLETED with honest FAILED suite check | `status=COMPLETED · overall=FAILED · suite=FAILED · comparison=UNRESOLVED(FAILED->FAILED) · retrieval=COMPLETE · artifact=DOCS_DIFF · planner=heuristic-v1 · paths=readme.md · documents=CONTRIBUTION_PLAN.md` | ✅ |
| 8 | Network attempt (malicious repo) | network attempt blocked; suite FAILED or refused NOT_RUN | `status=COMPLETED · overall=FAILED · suite=FAILED · comparison=UNRESOLVED(FAILED->FAILED) · retrieval=COMPLETE · artifact=DOCS_DIFF · planner=heuristic-v1 · paths=readme.md · documents=CONTRIBUTION_PLAN.md` | ✅ |
| 9 | GitHub rate limit (simulated) | typed RATE_LIMITED (simulated) | `status=FAILED · error=RATE_LIMITED` | ✅ |
| 9b | Model gateway failure (simulated) | typed MODEL_ERROR (simulated gateway failure) | `status=FAILED · error=MODEL_ERROR · retrieval=COMPLETE` | ✅ |
| 10 | Potential regression | POTENTIAL_REGRESSION/INCOMPLETE, never presented as fixed | `status=COMPLETED · overall=FAILED · suite=FAILED · comparison=POTENTIAL_REGRESSION(PASSED->FAILED) · retrieval=COMPLETE · artifact=PATCH_DIFF · planner=scripted-eval-v1 · paths=src/fixture/core.py · documents=CONTRIBUTION_PLAN.md,REPRO_CHECKLIST.md` | ✅ |
| 11 | Malformed URLs | typed INVALID_INPUT for every malformed URL | `errors=INVALID_INPUT,INVALID_INPUT,INVALID_INPUT,INVALID_INPUT` | ✅ |
| 12 | Nonexistent repository | typed NETWORK_ERROR | `status=FAILED · error=NETWORK_ERROR` | ✅ |

Rows 1–2 of docs/evaluation.md (live GitHub runs) are covered by the opt-in
network e2e test (`pytest -m network tests/e2e/test_live_github.py`) and the
browser-to-artifact evidence in
`docs/evaluation-runs/browser_tabulate_481/`; the public-repository
results are summarized in `docs/evaluation-real-results.md`.
