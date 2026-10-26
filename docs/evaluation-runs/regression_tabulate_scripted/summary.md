# A patch that breaks a passing check is a potential regression

- **Case:** `regression_tabulate_scripted`
- **Repository:** `astanin/python-tabulate`
- **Input:** https://github.com/astanin/python-tabulate — “Adjust the left-padding implementation for the table renderer.”
- **Upstream commit:** `268615a5c27dc40e5c22454c07b44d5c50410da0`
- **Prepared commit:** `be57b71b53a4278d80159e5ed68bd33343bb51ec`
- **Planner observed:** `scripted-eval-v1`
- **Status:** `COMPLETED`
- **Expected:** COMPLETED with POTENTIAL_REGRESSION, never presented as fixed
- **Verdict:** PASS — baseline=PASSED -> post=FAILED; POTENTIAL_REGRESSION; the run is not presented as fixed

## Injected test / fault

Committed a passing contract test on top of upstream so the baseline comparison can detect the scripted regression.

- `test/test_padding_contract.py`

## Retrieval

- **Status:** `COMPLETE`
- **Files:** 19 examined of 19 eligible (27 tracked)
- **Evidence records:** 8
- **Summary:** Retrieval is COMPLETE: examined 19 of 19 eligible file(s) from 27 tracked file(s), read 369793 byte(s), and retained 15 matching file(s). No retrieval limit was reached.


## Artifact

- **Kind:** `PATCH_DIFF`
- **Paths:** `tabulate/__init__.py`
- **Patch lines:** 13

## Documents

- `CONTRIBUTION_PLAN.md` (CONTRIBUTION_PLAN)
- `REPRO_CHECKLIST.md` (REPRO_CHECKLIST)

## Receipt

| Check | Status | Detail |
|---|---|---|
| `patch-path-policy` | `PASSED` |  |
| `patch-applies-on-pinned-commit` | `PASSED` |  |
| `sandbox-egress-isolation` | `PASSED` | every egress attempt from inside the sandbox was refused |
| `repository-test-suite` | `FAILED` | :test_alignment_of_link_text_cells - Assertion... FAILED test/test_regression.py::test_datetime_values - AssertionError FAILED test/test_regression.py::test_simple_separated_format |

## Comparison

- **Outcome:** `POTENTIAL_REGRESSION`
- **Baseline:** `PASSED`
- **Post-patch:** `FAILED`
- **Interpretation:** the selected check passed before the patch and failed after it; a potential regression is present

### Baseline output tail

```
EADME.md .                                                              [  0%]
tabulate/__init__.py ................                                    [  4%]
test/test_api.py ...                                                     [  5%]
test/test_cli.py .............................                           [ 12%]
test/test_grapheme_clusters.py .................                         [ 17%]
test/test_input.py .......sssssssss.................                     [ 25%]
test/test_internal.py ......................                             [ 31%]
test/test_output.py .................................................... [ 45%]
........................................................................ [ 63%]
..........................................s..................ssss....... [ 82%]
.....                                                                    [ 83%]
test/test_padding_contract.py .                                          [ 84%]
test/test_regression.py ......................s.........s...s.....       [ 95%]
test/test_textwrapper.py ...................                             [100%]

======================= 367 passed, 17 skipped in 3.27s ========================
```

### Post-patch output tail

```
tiline_with_wide_characters - Asserti...
FAILED test/test_regression.py::test_boolean_columns - AssertionError
FAILED test/test_regression.py::test_escape_empty_cell_in_first_column_in_rst
FAILED test/test_regression.py::test_empty_pipe_table_with_columns - Assertio...
FAILED test/test_regression.py::test_custom_tablefmt - AssertionError
FAILED test/test_regression.py::test_preserve_line_breaks_with_maxcolwidths
FAILED test/test_regression.py::test_maxcolwidths_accepts_list_or_tuple - Ass...
FAILED test/test_regression.py::test_empty_table_with_colalign - AssertionError
FAILED test/test_regression.py::test_empty_table_with_maxheadercolwidths - As...
FAILED test/test_regression.py::test_asciidoc_without_trailing_whitespace - A...
FAILED test/test_regression.py::test_github_escape_pipe_character - Assertion...
FAILED test/test_textwrapper.py::test_wrap_datetime - AssertionError
FAILED test/test_textwrapper.py::test_wrap_none_value - AssertionError
FAILED test/test_textwrapper.py::test_wrap_none_value_with_missingval - Asser...
FAILED test/test_textwrapper.py::test_wrap_optional_bool_strs - AssertionError
================= 216 failed, 151 passed, 17 skipped in 11.37s =================
```

## Provenance

- Case workspace: `var/eval-real/cases/regression_tabulate_scripted`
- Elapsed: 19.81s
- Sandbox backend: `bwrap`
- Planner requested: `scripted`

## Notes

A committed test asserts the current grid output. The scripted patch adds an extra padding column, so baseline passes and post-patch fails.
