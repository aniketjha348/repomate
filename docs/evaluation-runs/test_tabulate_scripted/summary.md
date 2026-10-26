# Test-addition task

- **Case:** `test_tabulate_scripted`
- **Repository:** `astanin/python-tabulate`
- **Input:** https://github.com/astanin/python-tabulate — “Add a regression test for the simple grid output in the test suite.”
- **Upstream commit:** `268615a5c27dc40e5c22454c07b44d5c50410da0`
- **Prepared commit:** `268615a5c27dc40e5c22454c07b44d5c50410da0`
- **Planner observed:** `scripted-eval-v1`
- **Status:** `COMPLETED`
- **Expected:** COMPLETED, TEST_DIFF, CONTRIBUTION_PLAN.md, passing suite
- **Verdict:** PASS — TEST_DIFF; suite=PASSED; NO_REGRESSION_DETECTED

## Retrieval

- **Status:** `COMPLETE`
- **Files:** 18 examined of 18 eligible (26 tracked)
- **Evidence records:** 8
- **Summary:** Retrieval is COMPLETE: examined 18 of 18 eligible file(s) from 26 tracked file(s), read 369616 byte(s), and retained 14 matching file(s). No retrieval limit was reached.


## Artifact

- **Kind:** `TEST_DIFF`
- **Paths:** `test/test_grid_contract.py`
- **Patch lines:** 13

## Documents

- `CONTRIBUTION_PLAN.md` (CONTRIBUTION_PLAN)

## Receipt

| Check | Status | Detail |
|---|---|---|
| `patch-path-policy` | `PASSED` |  |
| `patch-applies-on-pinned-commit` | `PASSED` |  |
| `sandbox-egress-isolation` | `PASSED` | every egress attempt from inside the sandbox was refused |
| `repository-test-suite` | `PASSED` | ============================= test session starts ============================== platform linux -- Python 3.14.4, pytest-9.1.1, pluggy-1.7.0 rootdir: /tmp/repomate-verify-f0rx304v/ |

## Comparison

- **Outcome:** `NO_REGRESSION_DETECTED`
- **Baseline:** `PASSED`
- **Post-patch:** `PASSED`
- **Interpretation:** the selected check passed before and after the patch; no regression was detected in the selected check

### Baseline output tail

```
baseline
configfile: pyproject.toml
plugins: anyio-4.15.1
collected 383 items

README.md .                                                              [  0%]
tabulate/__init__.py ................                                    [  4%]
test/test_api.py ...                                                     [  5%]
test/test_cli.py .............................                           [ 12%]
test/test_grapheme_clusters.py .................                         [ 17%]
test/test_input.py .......sssssssss.................                     [ 25%]
test/test_internal.py ......................                             [ 31%]
test/test_output.py .................................................... [ 45%]
........................................................................ [ 63%]
..........................................s..................ssss....... [ 82%]
.....                                                                    [ 84%]
test/test_regression.py ......................s.........s...s.....       [ 95%]
test/test_textwrapper.py ...................                             [100%]

======================= 366 passed, 17 skipped in 2.93s ========================
```

### Post-patch output tail

```
EADME.md .                                                              [  0%]
tabulate/__init__.py ................                                    [  4%]
test/test_api.py ...                                                     [  5%]
test/test_cli.py .............................                           [ 12%]
test/test_grapheme_clusters.py .................                         [ 17%]
test/test_grid_contract.py .                                             [ 17%]
test/test_input.py .......sssssssss.................                     [ 26%]
test/test_internal.py ......................                             [ 31%]
test/test_output.py .................................................... [ 45%]
........................................................................ [ 64%]
..........................................s..................ssss....... [ 82%]
.....                                                                    [ 84%]
test/test_regression.py ......................s.........s...s.....       [ 95%]
test/test_textwrapper.py ...................                             [100%]

======================= 367 passed, 17 skipped in 2.96s ========================
```

## Provenance

- Case workspace: `var/eval-real/cases/test_tabulate_scripted`
- Elapsed: 9.7s
- Sandbox backend: `bwrap`
- Planner requested: `scripted`

## Notes

Scripted TEST plan creates a new test file. The baseline and post-patch suites must both pass; the artifact is labelled TEST_DIFF rather than PATCH_DIFF.
