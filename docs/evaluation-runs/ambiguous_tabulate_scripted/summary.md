# Ambiguous task asking for more information

- **Case:** `ambiguous_tabulate_scripted`
- **Repository:** `astanin/python-tabulate`
- **Input:** https://github.com/astanin/python-tabulate — “Make the table output nicer.”
- **Upstream commit:** `268615a5c27dc40e5c22454c07b44d5c50410da0`
- **Prepared commit:** `268615a5c27dc40e5c22454c07b44d5c50410da0`
- **Planner observed:** `scripted-eval-v1`
- **Status:** `NEED_MORE_INFO`
- **Expected:** NEED_MORE_INFO with explicit questions and a downloadable plan
- **Verdict:** PASS — NEED_MORE_INFO with 3 question(s); plan document present

## Retrieval

- **Status:** `COMPLETE`
- **Files:** 18 examined of 18 eligible (26 tracked)
- **Evidence records:** 8
- **Summary:** Retrieval is COMPLETE: examined 18 of 18 eligible file(s) from 26 tracked file(s), read 369616 byte(s), and retained 14 matching file(s). No retrieval limit was reached.


## Documents

- `CONTRIBUTION_PLAN.md` (CONTRIBUTION_PLAN)

## Provenance

- Case workspace: `var/eval-real/cases/ambiguous_tabulate_scripted`
- Elapsed: 0.63s
- Sandbox backend: `bwrap`
- Planner requested: `scripted`

## Notes

Scripted plan sets need_more_info. The evidence collection and plan document are real; the ambiguity is intentional.
