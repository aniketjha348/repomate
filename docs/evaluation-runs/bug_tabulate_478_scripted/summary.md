# Reproducible bug with a relevant regression test

- **Case:** `bug_tabulate_478_scripted`
- **Repository:** `astanin/python-tabulate`
- **Input:** https://github.com/astanin/python-tabulate/issues/478
- **Upstream commit:** `268615a5c27dc40e5c22454c07b44d5c50410da0`
- **Prepared commit:** `df8421880b41229b51edee238d87f689bf96e5b0`
- **Planner observed:** `scripted-eval-v1`
- **Status:** `COMPLETED`
- **Expected:** COMPLETED, PATCH_DIFF, plan + repro checklist, CONSISTENT_IMPROVEMENT
- **Verdict:** PASS — baseline=FAILED -> post=PASSED; PATCH_DIFF

## Injected test / fault

Committed a regression test on top of the real upstream commit so the baseline comparison can observe the bug.

- `test/test_issue_478_regression.py`

## Retrieval

- **Status:** `COMPLETE`
- **Files:** 19 examined of 19 eligible (27 tracked)
- **Evidence records:** 8
- **Summary:** Retrieval is COMPLETE: examined 19 of 19 eligible file(s) from 27 tracked file(s), read 369891 byte(s), and retained 16 matching file(s). No retrieval limit was reached.


## Artifact

- **Kind:** `PATCH_DIFF`
- **Paths:** `tabulate/__init__.py`
- **Patch lines:** 14

## Documents

- `CONTRIBUTION_PLAN.md` (CONTRIBUTION_PLAN)
- `REPRO_CHECKLIST.md` (REPRO_CHECKLIST)

## Receipt

| Check | Status | Detail |
|---|---|---|
| `patch-path-policy` | `PASSED` |  |
| `patch-applies-on-pinned-commit` | `PASSED` |  |
| `sandbox-egress-isolation` | `PASSED` | every egress attempt from inside the sandbox was refused |
| `repository-test-suite` | `PASSED` | ============================= test session starts ============================== platform linux -- Python 3.14.4, pytest-9.1.1, pluggy-1.7.0 rootdir: /tmp/repomate-verify-hkgwo4m2/ |

## Comparison

- **Outcome:** `CONSISTENT_IMPROVEMENT`
- **Baseline:** `FAILED`
- **Post-patch:** `PASSED`
- **Interpretation:** the selected check failed on the clean baseline commit and passed after applying the patch; consistent improvement, not final proof of correctness

### Baseline output tail

```
.....................................s..................ssss....... [ 82%]
.....                                                                    [ 84%]
test/test_regression.py ......................s.........s...s.....       [ 95%]
test/test_textwrapper.py ...................                             [100%]

=================================== FAILURES ===================================
____________________ test_wrapped_wide_char_lines_fit_width ____________________

    def test_wrapped_wide_char_lines_fit_width():
        lines = _CustomTextWrap(width=3).wrap("a 글글")
        widths = [wcwidth.wcswidth(line) for line in lines]
>       assert all(width <= 3 for width in widths), (lines, widths)
E       AssertionError: (['a 글', '글'], [4, 2])
E       assert False
E        +  where False = all(<generator object test_wrapped_wide_char_lines_fit_width.<locals>.<genexpr> at 0x770b863724d0>)

test/test_issue_478_regression.py:9: AssertionError
=========================== short test summary info ============================
FAILED test/test_issue_478_regression.py::test_wrapped_wide_char_lines_fit_width
================== 1 failed, 366 passed, 17 skipped in 3.07s ===================
```

### Post-patch output tail

```
EADME.md .                                                              [  0%]
tabulate/__init__.py ................                                    [  4%]
test/test_api.py ...                                                     [  5%]
test/test_cli.py .............................                           [ 12%]
test/test_grapheme_clusters.py .................                         [ 17%]
test/test_input.py .......sssssssss.................                     [ 25%]
test/test_internal.py ......................                             [ 31%]
test/test_issue_478_regression.py .                                      [ 31%]
test/test_output.py .................................................... [ 45%]
........................................................................ [ 64%]
..........................................s..................ssss....... [ 82%]
.....                                                                    [ 84%]
test/test_regression.py ......................s.........s...s.....       [ 95%]
test/test_textwrapper.py ...................                             [100%]

======================= 367 passed, 17 skipped in 2.68s ========================
```

## Provenance

- Case workspace: `var/eval-real/cases/bug_tabulate_478_scripted`
- Elapsed: 10.46s
- Sandbox backend: `bwrap`
- Planner requested: `scripted`

## Notes

A regression test for issue #478 is committed on top of upstream 268615a. Baseline fails on the test; the scripted patch restores the width guard and post-patch passes.
