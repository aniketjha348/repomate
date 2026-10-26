# Missing license is surfaced, not hidden

- **Case:** `missing_license_hello_world`
- **Repository:** `octocat/Hello-World`
- **Input:** https://github.com/octocat/Hello-World — “Add a short usage note to the README.”
- **Upstream commit:** `7fd1a60b01f91b314f59955a4e4d4e80d8edf11d`
- **Prepared commit:** `7fd1a60b01f91b314f59955a4e4d4e80d8edf11d`
- **Planner observed:** `heuristic-v1`
- **Status:** `NEED_MORE_INFO`
- **Expected:** COMPLETED with the license status visible in the plan and the repository suite NOT_RUN
- **Verdict:** FAIL — expected COMPLETED; observed status=NEED_MORE_INFO

## Retrieval

- **Status:** `COMPLETE`
- **Files:** 0 examined of 0 eligible (1 tracked)
- **Evidence records:** 0
- **Summary:** Retrieval is COMPLETE: examined 0 of 0 eligible file(s) from 1 tracked file(s), read 0 byte(s), and retained 0 matching file(s). No retrieval limit was reached.


## Documents

- `CONTRIBUTION_PLAN.md` (CONTRIBUTION_PLAN)

## Provenance

- Case workspace: `var/eval-real/cases/missing_license_hello_world`
- Elapsed: 0.21s
- Sandbox backend: `bwrap`
- Planner requested: `scripted`

## Notes

octocat/Hello-World has no license file. RepoMate must report that state in the plan rather than implying a license.
