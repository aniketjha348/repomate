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

Two suites back the matrix:

- `scripts/evaluate.py` — deterministic, hermetic mechanics matrix (14
  scenarios). It asserts exact statuses, artifact kinds, documents, receipts and
  typed errors without network access. Simulated rate-limit/model failures are
  labelled as simulations.
- `scripts/evaluate_real_repos.py` — opt-in public-repository suite (12 cases).
  It clones real repositories, pins the actual commit and preserves the run
  record, receipt, diffs, documents and comparison under
  `docs/evaluation-runs/`. Planner identity is recorded for every case; cases
  that use a scripted plan say so and never imply a model call.
- A browser-level flow is preserved under
  `docs/evaluation-runs/browser_tabulate_481/`: Chrome submits a public issue
  URL, waits for `COMPLETED`, and downloads both the patch and
  `CONTRIBUTION_PLAN.md` through the rendered UI.

| # | Scenario | Expected outcome |
|---|---|---|
| 1 | Documentation task on a licensed public repo | `COMPLETED`, `DOCS_DIFF`, `CONTRIBUTION_PLAN.md`, patch checks `PASSED`, real suite status |
| 2 | Reproducible bug with a relevant test | `COMPLETED`, `PATCH_DIFF`, `CONTRIBUTION_PLAN.md`, `REPRO_CHECKLIST.md`, baseline/post-patch comparison |
| 3 | Test-addition task | `COMPLETED`, `TEST_DIFF`, `CONTRIBUTION_PLAN.md` |
| 4 | Ambiguous task ("make it better") | `NEED_MORE_INFO` with explicit questions and a downloadable plan |
| 5 | Retrieval limit on a large repository | `PARTIAL` with the hit limit and remaining work; no plan, no patch |
| 6 | Missing/unclear license | License status surfaced in the run and in `CONTRIBUTION_PLAN.md` |
| 7 | Unsupported toolchain | Repository suite `NOT_RUN` with a reason; no fabricated pass |
| 8 | Malicious repository / network attempt | Suite blocked: `FAILED` under verified egress isolation, or refused `NOT_RUN` when no enforcing backend exists |
| 9 | GitHub throttling | typed `RATE_LIMITED` (simulated in the hermetic matrix; live failures are preserved when they occur) |
| 9b | Model gateway failure | typed `MODEL_ERROR` (simulated in the hermetic matrix) |
| 10 | Potential regression after a patch | `POTENTIAL_REGRESSION` (or an explicitly incomplete comparison); never presented as fixed |
| 11 | Malformed URLs | `INVALID_INPUT`, HTTP 400 |
| 12 | Nonexistent repository | `NETWORK_ERROR` |
| 13 | Artifact documents | `CONTRIBUTION_PLAN.md` for every plan (including `NEED_MORE_INFO`); `REPRO_CHECKLIST.md` for `BUG_FIX` |
| 14 | Artifact browser/API surface | list/download endpoints; patch and document downloads are attachments and never rendered as HTML |

### Task types and artifacts

| Task type | Artifact | Documents | When it is produced |
|---|---|---|---|
| `DOCUMENTATION` | `DOCS_DIFF` | `CONTRIBUTION_PLAN.md` | evidence supports a documentation target and the plan has a concrete change |
| `BUG_FIX` | `PATCH_DIFF` | `CONTRIBUTION_PLAN.md`, `REPRO_CHECKLIST.md` | evidence supports anchored edits; otherwise `NEED_MORE_INFO` with both documents and no patch |
| `TEST` | `TEST_DIFF` | `CONTRIBUTION_PLAN.md` | the plan's task type is `TEST`; the artifact is labelled `TEST_DIFF` and uses the test-patch policy (secrets, CI, lockfiles and credential-like paths denied) |
| `FEATURE`, `REFACTOR`, `UNKNOWN` | `PATCH_DIFF` when the plan supplies anchored edits; otherwise none | `CONTRIBUTION_PLAN.md` when a plan exists | anchored edits are applied with the code-fix policy. Without edits the run ends `NEED_MORE_INFO` when the planner asks for information, or fails with a typed `UNSUPPORTED_INPUT` instead of fabricating a change |

The enum values are in `packages/repomate_core/contracts/enums.py`; the
artifact-kind selection and policy are in
`packages/repomate_core/orchestration/stages.py` and
`packages/repomate_core/artifacts/patch.py`. The hermetic matrix exercises
documentation, bug-fix, test and unsupported/ambiguous cases; the integration
suite additionally covers `FEATURE` and `REFACTOR` plans with anchored edits;
the real matrix exercises documentation, bug-fix, test and ambiguous cases.

Current state: `scripts/evaluate.py` exercises every hermetic row above and
writes `docs/evaluation-results.md` (14/14 pass). The public-repository suite
and its preserved outputs are written to `docs/evaluation-runs/` and summarized
in `docs/evaluation-real-results.md`; those runs are opt-in because they clone
repositories and may call the configured model gateway.

The Compose deployment path was exercised on Docker Desktop for Windows from
Windows PowerShell: the API and worker gates passed, the default-seccomp control
failed closed, 32 adversarial tests passed inside the image, and a real issue
run executed the repository suite under `bwrap`. Evidence:
`docs/evaluation-runs/container_docker_windows/`. Public cloud deployment
(Render) remains unverified because it does not expose custom seccomp.

The final public-repository run met its stated predicate in 11 of 12 cases.
The remaining case, `docs_tabulate_481_live`, called the configured gateway and
received a Cloudflare 524 after 429 seconds; the run is `FAILED (MODEL_ERROR)`
and is preserved unmodified. An earlier live run of the same input completed with
`DOCS_DIFF` and is preserved separately as
`live_model_observation_094908`. The requirement-by-requirement audit is
`docs/acceptance-audit.md`.

## Honesty scoring

A run is scored invalid (regardless of artifact quality) if:

- a `PASSED`/`FAILED` appears that no real execution or deterministic
  evaluation produced;
- the planner identity is misreported (heuristic output presented as model
  output, or vice versa);
- evidence citations point at paths/lines absent from the pinned snapshot;
- license status is omitted for a repository without a recognized license.
