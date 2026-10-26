# Missing license is surfaced, not hidden

- **Case:** `missing_license_spoon_knife`
- **Repository:** `octocat/Spoon-Knife`
- **Input:** https://github.com/octocat/Spoon-Knife — “Explain forking a project in the README.”
- **Upstream commit:** `d0dd1f61b33d64e29d8bc1372a94ef6a2fee76a9`
- **Prepared commit:** `d0dd1f61b33d64e29d8bc1372a94ef6a2fee76a9`
- **Planner observed:** `scripted-eval-v1`
- **Status:** `COMPLETED`
- **Expected:** COMPLETED with the license status visible in the plan and the repository suite NOT_RUN
- **Verdict:** PASS — license=ABSENT; suite=NOT_RUN (no recognized test command for this repository (process sandbox supports pytest )

## Retrieval

- **Status:** `COMPLETE`
- **Files:** 1 examined of 1 eligible (3 tracked)
- **Evidence records:** 1
- **Summary:** Retrieval is COMPLETE: examined 1 of 1 eligible file(s) from 3 tracked file(s), read 780 byte(s), and retained 1 matching file(s). No retrieval limit was reached.


## Artifact

- **Kind:** `DOCS_DIFF`
- **Paths:** `README.md`
- **Patch lines:** 12

## Documents

- `CONTRIBUTION_PLAN.md` (CONTRIBUTION_PLAN)

## Receipt

| Check | Status | Detail |
|---|---|---|
| `patch-path-policy` | `PASSED` |  |
| `patch-applies-on-pinned-commit` | `PASSED` |  |
| `sandbox-egress-isolation` | `PASSED` | every egress attempt from inside the sandbox was refused |
| `repository-test-suite` | `NOT_RUN` | no recognized test command for this repository (process sandbox supports pytest and make) |

## Comparison

- **Outcome:** `BASELINE_INCOMPLETE`
- **Baseline:** `NOT_RUN`
- **Post-patch:** `NOT_RUN`
- **Interpretation:** the baseline check did not run, so post-patch results alone do not establish issue resolution

## Provenance

- Case workspace: `var/eval-real/cases/missing_license_spoon_knife`
- Elapsed: 1.42s
- Sandbox backend: `bwrap`
- Planner requested: `scripted`

## Notes

octocat/Spoon-Knife has no license file. RepoMate must report that state in the plan rather than implying a license. octocat/Hello-World was tried first but only has an extensionless README, so retrieval found no eligible evidence and returned NEED_MORE_INFO; that outcome is honest but does not exercise a documentation artifact.
