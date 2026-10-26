# Large repository stops at the retrieval limit

- **Case:** `large_django_partial`
- **Repository:** `django/django`
- **Input:** https://github.com/django/django — “Add a note about running the test suite to the contributing documentation.”
- **Upstream commit:** `a2a0b4f2764f7b192bff4bb75ed56ce017931a71`
- **Prepared commit:** `a2a0b4f2764f7b192bff4bb75ed56ce017931a71`
- **Planner observed:** `none`
- **Status:** `PARTIAL`
- **Expected:** PARTIAL with a recorded limit hit; no plan and no patch
- **Verdict:** PASS — retrieval=PARTIAL; hits=MAX_SEARCH_RESULTS; examined 822/3776 eligible files

## Retrieval

- **Status:** `PARTIAL`
- **Files:** 822 examined of 3776 eligible (7089 tracked)
- **Evidence records:** 8
- **Summary:** Retrieval is PARTIAL: examined 822 of 3776 eligible file(s) from 7089 tracked file(s), read 5065824 byte(s), and retained 200 matching file(s). 2954 eligible file(s) were not examined. Limits reached: MAX_SEARCH_RESULTS. This analysis does not cover the whole repository.

- Limit `MAX_SEARCH_RESULTS`: allowed 200, observed 201. django/tasks/exceptions.py matched but was not retained, and any lower-ranked matches were not considered; 2954 eligible file(s) were not examined because the 200-result search cap was reached.

## Provenance

- Case workspace: `var/eval-real/cases/large_django_partial`
- Elapsed: 19.58s
- Sandbox backend: `bwrap`
- Planner requested: `none`

## Notes

django/django has 7089 tracked files. Retrieval hits the MAX_SEARCH_RESULTS cap, so the run stops before planning.
