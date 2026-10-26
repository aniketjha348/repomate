# Unreachable model gateway maps to a typed MODEL_ERROR

- **Case:** `model_failure_tabulate`
- **Repository:** `astanin/python-tabulate`
- **Input:** https://github.com/astanin/python-tabulate — “Document the width guard in the README.”
- **Upstream commit:** `268615a5c27dc40e5c22454c07b44d5c50410da0`
- **Prepared commit:** `268615a5c27dc40e5c22454c07b44d5c50410da0`
- **Planner observed:** `model:openai/eval-unreachable`
- **Status:** `FAILED`
- **Expected:** FAILED with ErrorCode.MODEL_ERROR and no artifact
- **Verdict:** PASS — FAILED with MODEL_ERROR; no artifact

## Error

- **Code:** `MODEL_ERROR`
- **Message:** model gateway unreachable: [Errno 111] Connection refused

## Retrieval

- **Status:** `COMPLETE`
- **Files:** 18 examined of 18 eligible (26 tracked)
- **Evidence records:** 8
- **Summary:** Retrieval is COMPLETE: examined 18 of 18 eligible file(s) from 26 tracked file(s), read 369616 byte(s), and retained 11 matching file(s). No retrieval limit was reached.


## Provenance

- Case workspace: `var/eval-real/cases/model_failure_tabulate`
- Elapsed: 0.56s
- Sandbox backend: `bwrap`
- Planner requested: `failing-model`

## Notes

The planner points at https://127.0.0.1:9/v1 with retries disabled. The transport failure is real; the endpoint is a deliberately unreachable loopback address.
