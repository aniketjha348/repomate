# Real-Repository Evaluation Results

Generated 2026-10-26T10:04:23.345354+00:00 by `scripts/evaluate_real_repos.py`.

These runs clone real public repositories. Scripted plans are labelled; injected tests and fault injections are recorded in each case's `provenance.json` and `summary.md`.

## Environment

- Platform: linux
- Python: 3.14.4
- Sandbox backend: `bwrap`
- Test suite command: `python -m pytest -q (inside the sandbox)`
- Live model: `deepseek-v4.1`

## Results

| # | Case | Repository | Prepared commit | Planner | Outcome | Verdict |
|---|---|---|---|---|---|---|
| 1 | [`docs_tabulate_481_scripted`](evaluation-runs/docs_tabulate_481_scripted/summary.md) | `astanin/python-tabulate` | `268615a5c2` | `scripted-eval-v1` | `COMPLETED` | ✅ PASS |
| 2 | [`docs_tabulate_481_live`](evaluation-runs/docs_tabulate_481_live/summary.md) | `astanin/python-tabulate` | `268615a5c2` | `model:openai/deepseek-v4.1` | `FAILED (MODEL_ERROR)` | ❌ FAIL |
| 3 | [`bug_tabulate_478_scripted`](evaluation-runs/bug_tabulate_478_scripted/summary.md) | `astanin/python-tabulate` | `df8421880b` | `scripted-eval-v1` | `COMPLETED` | ✅ PASS |
| 4 | [`test_tabulate_scripted`](evaluation-runs/test_tabulate_scripted/summary.md) | `astanin/python-tabulate` | `268615a5c2` | `scripted-eval-v1` | `COMPLETED` | ✅ PASS |
| 5 | [`ambiguous_tabulate_scripted`](evaluation-runs/ambiguous_tabulate_scripted/summary.md) | `astanin/python-tabulate` | `268615a5c2` | `scripted-eval-v1` | `NEED_MORE_INFO` | ✅ PASS |
| 6 | [`large_django_partial`](evaluation-runs/large_django_partial/summary.md) | `django/django` | `a2a0b4f276` | `none` | `PARTIAL` | ✅ PASS |
| 7 | [`missing_license_spoon_knife`](evaluation-runs/missing_license_spoon_knife/summary.md) | `octocat/Spoon-Knife` | `d0dd1f61b3` | `scripted-eval-v1` | `COMPLETED` | ✅ PASS |
| 8 | [`unavailable_toolchain_pyparsing`](evaluation-runs/unavailable_toolchain_pyparsing/summary.md) | `pyparsing/pyparsing` | `810199f89b` | `scripted-eval-v1` | `COMPLETED` | ✅ PASS |
| 9 | [`network_tabulate_scripted`](evaluation-runs/network_tabulate_scripted/summary.md) | `astanin/python-tabulate` | `8d0ab6b207` | `scripted-eval-v1` | `COMPLETED` | ✅ PASS |
| 10 | [`github_rate_limit_injected`](evaluation-runs/github_rate_limit_injected/summary.md) | `astanin/python-tabulate` | `268615a5c2` | `none` | `FAILED (RATE_LIMITED)` | ✅ PASS |
| 11 | [`model_failure_tabulate`](evaluation-runs/model_failure_tabulate/summary.md) | `astanin/python-tabulate` | `268615a5c2` | `model:openai/eval-unreachable` | `FAILED (MODEL_ERROR)` | ✅ PASS |
| 12 | [`regression_tabulate_scripted`](evaluation-runs/regression_tabulate_scripted/summary.md) | `astanin/python-tabulate` | `be57b71b53` | `scripted-eval-v1` | `COMPLETED` | ✅ PASS |

Each linked summary preserves the input, upstream and prepared commits, evidence, artifact, receipt and comparison. Raw run records are in `evaluation-runs/<case>/run.json`.

## Browser-to-artifact proof

A separate browser run (`run_20261026-100340_8a5rrl53`) submitted issue #481 through the Next.js UI, reached `COMPLETED`, rendered the diff and receipt, and downloaded the patch and `CONTRIBUTION_PLAN.md`. The screenshot, DOM text, run record and downloaded files are preserved in [`evaluation-runs/browser_tabulate_481/`](evaluation-runs/browser_tabulate_481/summary.md). The demo API was started without model credentials, so that planner is the deterministic `heuristic-v1`.

## Container deployment proof

The same Compose images were rebuilt and exercised on Docker Desktop for Windows (Linux containers, Engine 29.7.2) from Windows PowerShell. The API and worker egress gates passed with `backend=bwrap`; the container could reach the network without the sandbox, while the default Docker seccomp profile failed closed. All 32 adversarial egress tests passed inside the API image, and a real issue run (`run_20261026-103949_gxr0b2xr`) completed with `DOCS_DIFF`, `CONTRIBUTION_PLAN.md`, and a receipt showing 366 tests per checkout under `bwrap`. Raw gates, negative controls, logs and downloads are in [`evaluation-runs/container_docker_windows/`](evaluation-runs/container_docker_windows/summary.md). This is not a public cloud deployment claim.

## Observed failures and limitations

- **docs_tabulate_481_live** — live gateway failure preserved as a typed MODEL_ERROR: model gateway error (status 524); no artifact is claimed.

Concrete observed failures/limitations:

- **Live gateway timeout.** The final live-model case called `deepseek-v4.1` and received a Cloudflare 524 after 429 seconds. The run is `FAILED (MODEL_ERROR)`, no artifact is claimed, and the raw gateway body is preserved in its summary. An earlier run of the same input at 2026-10-26T09:49Z completed with `DOCS_DIFF`, preserved as `evaluation-runs/live_model_observation_094908/`; the failure was not deleted or presented as a success.
- **Public cloud deployment still not verified.** The Compose path itself was
  verified separately on Docker Desktop for Windows: both release gates passed,
  the default-seccomp control failed closed, 32 adversarial tests passed inside
  the container, and a real issue run completed with 366 tests executed under
  `bwrap` (`run_20261026-103949_gxr0b2xr`; see
  [`evaluation-runs/container_docker_windows/`](evaluation-runs/container_docker_windows/summary.md)).
  Render's Docker runtime does not expose custom seccomp, so that public
  deployment path remains `NOT_VERIFIED` and must fail closed.
- **Unauthenticated GitHub quota.** `GITHUB_TOKEN` was empty, so the REST API ran under the 60 req/h unauthenticated limit. The `RATE_LIMITED` handling is proven by an explicitly labelled fault injection, not by waiting for the live quota to exhaust.
- **Large-repository retrieval limit.** django/django (7,089 tracked files) correctly stopped as `PARTIAL` at the 200-result search cap; it did not produce a plan or patch.
- **Per-file evidence cap vs. toolchain case.** pyparsing's test suite needed a raised `max_bytes_per_file` to reach verification; with the default cap the run stopped `PARTIAL` before planning. The raised cap is recorded in that case's provenance and does not change the default.

Design limitations (not hidden test failures):

- Scripted plans exercise the real repository, evidence, artifact, sandbox and verification path, but the plan text is fixed by the harness. They are not evidence that the configured model would produce the same edit.
- The bug case adds a regression test as a local commit on top of the real upstream commit. The test is from the issue discussion; it is not shipped upstream.
- The network case and rate-limit case use explicit test/fault injection. They prove the control and error mapping, not that the live service was attacked or throttled.
- A `CONSISTENT_IMPROVEMENT` comparison is not proof of correctness; it means the selected check failed before and passed after the patch.
- RepoMate does not repair arbitrary issues. A run can end `NEED_MORE_INFO`, `PARTIAL`, `NOT_RUN`, `FAILED` or `POTENTIAL_REGRESSION`, and the UI and documents must show that outcome.
