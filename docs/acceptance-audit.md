# PS04 acceptance audit

Audit date: **2026-10-26**. This is a requirement-by-requirement audit of the
code and observed output, not an architecture summary. Statuses are `PASS`,
`FAIL`, or `NOT_VERIFIED`. A `PASS` names the implementation and the evidence
that exercised it; a `FAIL` or `NOT_VERIFIED` is not hidden in a footnote.

## Scope and method

- Hermetic matrix: `python scripts/evaluate.py` — 14 deterministic scenarios,
  no network. Results: [`docs/evaluation-results.md`](evaluation-results.md).
- Public-repository matrix: `python scripts/evaluate_real_repos.py` — 12 cases
  across `astanin/python-tabulate`, `django/django`, `octocat/Spoon-Knife` and
  `pyparsing/pyparsing`. Every case preserves its input, base/prepared commits,
  evidence, artifact, receipt, comparison and provenance under
  [`docs/evaluation-runs/`](evaluation-runs/).
- Browser proof: Chrome/Playwright submitted issue #481 through the Next.js UI,
  waited for a terminal record, rendered the plan/diff/receipt and downloaded
  the patch and plan. Evidence:
  [`docs/evaluation-runs/browser_tabulate_481/`](evaluation-runs/browser_tabulate_481/summary.md).
- Container gate: Docker Desktop for Windows (Linux containers) rebuilt both
  Compose images; the API and worker release gates passed, default seccomp
  failed closed, 32 adversarial tests passed in-container, and a real issue
  completed with 366 tests executed under `bwrap`. Evidence:
  [`docs/evaluation-runs/container_docker_windows/`](evaluation-runs/container_docker_windows/summary.md).
- Test suites were run on both hosts:
  - WSL/Linux with bubblewrap: **358 passed, 1 deselected** (`pytest -q`,
    164.06 s).
  - Windows: **307 passed, 51 skipped, 1 deselected** (119.74 s). Network
    sandbox checks are skipped because no egress-enforcement backend exists on
    Windows; that is reported as `NOT_RUN`, never a fabricated pass.
- `npx tsc --noEmit`, `npx next build`, `python -m compileall`, and
  `git diff --check` all completed successfully.

## Official PS04 criteria

| # | Requirement | Status | Implementation and observed evidence |
|---|---|---|---|
| 1 | Start a run from a public GitHub issue URL | **PASS** | `POST /api/runs` accepts `issue_url` (`services/api/routes/runs.py:25`); the UI validates the URL and starts the run (`apps/web/components/repository-input/issue-form.tsx`). Real issue cases #478/#481 and the browser run all started from public URLs. |
| 2 | Repository metadata and relevant source locations are verifiable | **PASS** | Snapshot orientation, license, evidence paths/line ranges and snippets are persisted (`packages/repomate_core/evidence/collector.py`; `docs/evaluation-runs/*/evidence.json`). Citations are checked against the pinned commit (`evidence/grounding.py`); unresolved citations are downgraded to hypotheses. Real runs show exact paths/lines and the UI renders them. |
| 3 | A contribution plan and at least one reviewable artifact are produced | **PASS** | Plans are persisted; artifacts are `DOCS_DIFF`, `PATCH_DIFF` or `TEST_DIFF` (`packages/repomate_core/contracts/enums.py:75`). Real docs, bug and test cases each produced a downloadable artifact; `NEED_MORE_INFO` runs still publish the plan. |
| 4 | Available checks execute and show real results, otherwise an explicit `NOT_RUN` reason | **PASS** | The sandbox executes the repository suite and records exit code/output (`verification/sandbox.py:430`). Real tabulate suites passed; pyparsing produced `NOT_RUN` with a dependency reason; Windows/no-backend hosts refuse execution by default. The receipt records baseline and post-patch runs separately (`orchestration/stages.py:318`). |
| 5 | The model's role and analysis limitations are explained | **PASS** | Every plan/artifact records `planned_by`/`generated_by` (`heuristic-v1`, `scripted-eval-v1`, or `model:...`); the UI shows it. The real matrix includes a live success and a real gateway failure; the browser demo is explicitly labelled heuristic. Grounding warnings and lexical-evidence limits are persisted and shown. |
| 6 | Artifacts are downloadable from the browser | **PASS** | `GET /api/runs/{id}/artifacts` lists outputs; patch and document downloads set `Content-Disposition: attachment` and `X-Content-Type-Options: nosniff` (`services/api/routes/artifacts.py:38,66,82`). Chrome downloaded `documentation.patch` (1,393 B) and `CONTRIBUTION_PLAN.md` (9,007 B); see the browser evidence. |
| 7 | Malformed input, model failure, GitHub throttling and unsupported tasks yield controlled errors | **PASS** | Invalid URLs → HTTP 400 `INVALID_INPUT`; repository failure → `NETWORK_ERROR`; model failure → `MODEL_ERROR` (`orchestration/pipeline.py:231`); GitHub throttle → `RATE_LIMITED` (`pipeline.py:245`); unsupported/ambiguous tasks → `NEED_MORE_INFO` with questions. The final live run observed a real 524 and preserved the typed error. GitHub throttling is proven by a labelled fault injection, not a live quota exhaustion. |
| 8 | Sandbox and secret-handling tests pass | **PASS** | `bwrap` egress isolation is enforced and probed (`verification/sandbox.py:578`); environment variables are scrubbed inside the sandbox (`tests/unit/test_sandbox.py::test_environment_is_scrubbed`). The egress pipeline test passes in WSL. The Compose API and worker gates also passed on Docker Desktop for Windows, the default-seccomp control failed closed, and 32 adversarial tests passed inside the container; see [`container_docker_windows`](evaluation-runs/container_docker_windows/summary.md). |

## Mandatory capability checks

| Capability | Status | Evidence |
|---|---|---|
| `CONTRIBUTION_PLAN.md` for every plan, including `NEED_MORE_INFO` | **PASS** | Renderer at `artifacts/documents.py:60`; published on every persist (`orchestration/context.py:121`). Tests: `test_test_task_produces_test_diff_and_plan_document`, `test_need_more_info_bug_still_publishes_plan_and_checklist`. |
| Artifact-list API | **PASS** | `GET /api/runs/{run_id}/artifacts` (`services/api/routes/artifacts.py:38`) returns name, kind, media type, size and download URL. Test: `test_artifact_listing_and_downloads`; browser rendered the links. |
| `TEST_DIFF` for `TEST` plans | **PASS** | `TEST_PATCH_POLICY` (`artifacts/patch.py:68`); selection in `orchestration/stages.py:337`. Real `test_tabulate_scripted` produced `TEST_DIFF`; hermetic test asserts the kind and path. |
| `REPRO_CHECKLIST.md` for `BUG_FIX` plans | **PASS** | Renderer at `artifacts/documents.py:157`; real bug #478 produced plan + checklist; test asserts baseline/post-patch language and honesty about unobserved failure. |
| Documented task types are handled, not merely declared | **PASS** | `TaskType`/`ArtifactKind` enums plus the task-type table in [`docs/evaluation.md`](evaluation.md#task-types-and-artifacts). `DOCUMENTATION`/`BUG_FIX`/`TEST` produce artifacts; `FEATURE`/`REFACTOR`/`UNKNOWN` produce `PATCH_DIFF` when the plan supplies anchored edits (`test_feature_and_refactor_plans_produce_patch_diff` covers both task types). Without edits the run ends `NEED_MORE_INFO` when the planner asks for information (real ambiguous case), or raises a typed `UNSUPPORTED_INPUT` (`orchestration/stages.py:303`) instead of fabricating a change. |
| Reproducible bug with a relevant test | **PASS** | `bug_tabulate_478_scripted`: injected regression test, baseline `FAILED` → post-patch `PASSED`, comparison `CONSISTENT_IMPROVEMENT`; patch restores the width guard. |
| Test-addition task | **PASS** | `test_tabulate_scripted`: `TEST_DIFF` touching `test/`, suite `PASSED`, comparison `NO_REGRESSION_DETECTED`. |
| Ambiguous task → `NEED_MORE_INFO` | **PASS** | `ambiguous_tabulate_scripted`: explicit questions, no artifact, downloadable plan with an “Open questions” section. |
| Large repository → `PARTIAL` | **PASS** | `large_django_partial`: 7,089 tracked files, 822/3,776 eligible examined, `MAX_SEARCH_RESULTS` hit recorded, no plan/patch. |
| Missing/unclear license surfaced | **PASS** | `missing_license_spoon_knife`: license `ABSENT` in snapshot and plan; suite `NOT_RUN` with a reason. |
| Unavailable toolchain → `NOT_RUN` | **PASS** | `unavailable_toolchain_pyparsing`: suite `NOT_RUN` due to missing `railroad`; the plan and docs artifact still complete. |
| Malicious/network repository | **PASS** | `network_tabulate_scripted`: injected HTTPS test fails under `bwrap`; receipt has `policy_enforced`, `egress_validation=PASSED`, suite `FAILED`. |
| GitHub throttling | **PASS** (fault-injected) | `github_rate_limit_injected`: typed `RATE_LIMITED`, no artifact; the injection is labelled in provenance. Live unauth quota exhaustion was not observed. |
| Model gateway failure | **PASS** | `model_failure_tabulate` (unreachable loopback) and the final live case (real Cloudflare 524) both end `FAILED (MODEL_ERROR)` with no artifact and a preserved reason. |
| Potential regression | **PASS** | `regression_tabulate_scripted`: baseline `PASSED` → post-patch `FAILED`, `POTENTIAL_REGRESSION`, never presented as fixed. |
| Downloads are attachments, not rendered HTML; 404/unknown names are safe | **PASS** | Artifact route sets `attachment` + `nosniff`; test asserts markdown content type, attachment and 404 for unknown names. |
| Metrics do not expose sensitive operational data | **PASS** | `services/api/routes/metrics.py` returns aggregate status/planner/fair-use counters only; test asserts `env_file` is absent and no string value contains a path. |
| No universal issue-fixing claim | **PASS** | README and evaluation docs state that `NEED_MORE_INFO`, `PARTIAL`, `NOT_RUN`, `FAILED` and `POTENTIAL_REGRESSION` are normal outcomes; `CONSISTENT_IMPROVEMENT` is explicitly not proof of correctness. |
| Working tree preserved, `.perch/` untouched, no commit made | **PASS** | Audit left the tree dirty (all changes uncommitted); `.perch/` is absent and was not created/removed. |

## Public-repository matrix

Final full run: **11 of 12 cases met their stated predicate**. This is the
actual result; the live failure is retained rather than replaced.

| Case | Observed | Verdict |
|---|---|---|
| `docs_tabulate_481_scripted` | `COMPLETED`, `DOCS_DIFF`, suite `PASSED` | PASS |
| `docs_tabulate_481_live` | `FAILED (MODEL_ERROR)`, gateway 524 after 429 s, no artifact | **FAIL** |
| `bug_tabulate_478_scripted` | `COMPLETED`, `PATCH_DIFF`, `FAILED`→`PASSED` | PASS |
| `test_tabulate_scripted` | `COMPLETED`, `TEST_DIFF`, suite `PASSED` | PASS |
| `ambiguous_tabulate_scripted` | `NEED_MORE_INFO`, 3 questions, plan document | PASS |
| `large_django_partial` | `PARTIAL`, limit hit, no plan/artifact | PASS |
| `missing_license_spoon_knife` | `COMPLETED`, license `ABSENT`, suite `NOT_RUN` | PASS |
| `unavailable_toolchain_pyparsing` | `COMPLETED`, `DOCS_DIFF`, suite `NOT_RUN` | PASS |
| `network_tabulate_scripted` | `COMPLETED`, egress blocked, suite `FAILED` | PASS |
| `github_rate_limit_injected` | `FAILED (RATE_LIMITED)`, no artifact | PASS |
| `model_failure_tabulate` | `FAILED (MODEL_ERROR)`, no artifact | PASS |
| `regression_tabulate_scripted` | `COMPLETED`, `POTENTIAL_REGRESSION` | PASS |

A prior live run of the same issue at `2026-10-26T09:49Z` completed with
`model:openai/deepseek-v4.1`, `DOCS_DIFF`, plan and a passing suite. It is
preserved separately as
[`live_model_observation_094908`](evaluation-runs/live_model_observation_094908/summary.md)
and is explicitly not a replacement for the final failure.

## Container deployment gate (Docker Desktop on Windows)

All Docker commands were run from Windows PowerShell with `docker.exe`; WSL
was not used to invoke Docker. Docker Desktop 4.88.1 / Engine 29.7.2 ran the
Linux containers. Images were rebuilt from the current tree.

| Check | Observed |
|---|---|
| API release gate (`scripts/verify_egress.py`) | exit 0; `backend=bwrap`, `policy_enforced=true`, `egress_validation=PASSED` |
| Worker release gate | exit 0; same `PASSED` sandbox record |
| Container without `bwrap` (control) | reached `1.1.1.1:80`; printed `control_reachable` |
| Default Docker seccomp (no custom profile) | exit 2; `policy_enforced=false`, `egress_validation=FAILED` — fail-closed |
| Adversarial suite in the API image | **32 passed** in 7.86 s |
| End-to-end issue run | `COMPLETED`, `DOCS_DIFF`, `CONTRIBUTION_PLAN.md`, suite `PASSED` (366 passed, 17 skipped) twice |

The end-to-end run is `run_20261026-103949_gxr0b2xr` for
https://github.com/astanin/python-tabulate/issues/481 at pinned commit
`268615a5c27dc40e5c22454c07b44d5c50410da0`. Its receipt records
`sandbox-egress-isolation: PASSED` and `repository-test-suite: PASSED`. Raw
records, gates, negative controls, images, logs and downloads:
[`evaluation-runs/container_docker_windows/`](evaluation-runs/container_docker_windows/summary.md).

This proves the container path on Docker Desktop's Linux VM. It does not prove
a public cloud deployment or a hardened multi-tenant runtime.

## Failures and limitations explained

1. **Live model gateway timeout (real failure).** The final `docs_tabulate_481_live`
   case spent 429 s calling `deepseek-v4.1` through the configured gateway and
   received a Cloudflare 524. RepoMate mapped it to `MODEL_ERROR`, recorded the
   model planner identity, produced no artifact, and left the run `FAILED`.
   This is an external availability failure, not a fabricated pass. An earlier
   live run succeeded, which shows the path works when the gateway responds;
   neither result is generalised into “the model always works”.
2. **Public cloud deployment remains `NOT_VERIFIED`.** The Compose path itself
   was verified on Docker Desktop for Windows on 2026-10-26: the API and worker
   gates exited 0, the default-seccomp control exited 2, 32 adversarial tests
   passed in-container, and a real issue completed with 366 tests executed under
   `bwrap`. Render's Docker runtime does not expose custom seccomp, so that
   public deployment path is still unverified; it fails closed. Docker Desktop
   on a developer Windows host is not a hardened multi-tenant runtime.
3. **Unauthenticated GitHub quota is a live operational limit.** `GITHUB_TOKEN`
   was empty, so the REST API was limited to 60 requests/hour. The
   `RATE_LIMITED` code path is verified by a labelled injection; a real quota
   exhaustion was not induced.
4. **Per-file evidence cap can stop a case before verification.** pyparsing's
   suite needed `max_bytes_per_file=1,000,000` to reach the toolchain check;
   with the default 200 KB cap the run correctly returned `PARTIAL` before
   planning. The raised cap is recorded in that case's provenance; the default
   is unchanged.
5. **Grounding is lexical, not semantic.** The browser run's heuristic plan had
   `0 supported / 5 hypothesis` claims and one unresolved evidence id; it
   still produced a plan and artifact with warnings. This is deliberately
   visible rather than presented as proof of relevance.
6. **Fair-use limiter is per-process.** The service is not scaled to multiple
   API replicas under public traffic. A shared/atomic limiter (Redis) does not
   exist yet, so horizontal scaling remains `NOT_VERIFIED` and is not claimed.

## Residual `NOT_VERIFIED` items

- Public cloud deployment (Render) and any runtime that cannot apply the custom
  seccomp profile; those paths must fail closed.
- Multiple API replicas with the fair-use limiter.
- Live GitHub quota exhaustion (only the injection is proven).
- `REPOMATE_SANDBOX_NETWORK=host` is an explicit trusted-local override. It is
  documented as unsafe for public use and was not used in this evaluation;
  without it, hosts with no enforcing backend return `NOT_RUN`.
- Universal issue-fixing: explicitly out of scope; the matrix demonstrates
  specific, evidence-backed outcomes and honest non-completion.

## Reproduce

```bash
# Hermetic 14-scenario matrix
python scripts/evaluate.py

# Public-repository matrix (WSL/Linux with bwrap; clones public repos)
python scripts/evaluate_real_repos.py

# Container gate (Docker Desktop; Linux containers)
docker compose -f deploy/compose.yaml up -d --build api worker
docker compose -f deploy/compose.yaml exec api python scripts/verify_egress.py
docker compose -f deploy/compose.yaml down

# Full test suites
pytest -q

# Frontend
cd apps/web && npx tsc --noEmit && npx next build
```

The preserved browser evidence was produced against a local API started
without model credentials:

```bash
REPOMATE_SKIP_DOTENV=1 OLLAMA_API_KEY= \
  REPOMATE_RUNS_ROOT=var/browser-demo/runs \
  uvicorn services.api.main:app --host 0.0.0.0 --port 8000
```
