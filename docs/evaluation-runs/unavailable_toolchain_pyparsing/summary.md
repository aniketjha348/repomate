# Unavailable test dependency is an explicit NOT_RUN

- **Case:** `unavailable_toolchain_pyparsing`
- **Repository:** `pyparsing/pyparsing`
- **Input:** https://github.com/pyparsing/pyparsing — “Document the original_text_for helper in the README.”
- **Upstream commit:** `810199f89bf916590426e1c5cb3d612584f11a2f`
- **Prepared commit:** `810199f89bf916590426e1c5cb3d612584f11a2f`
- **Planner observed:** `scripted-eval-v1`
- **Status:** `COMPLETED`
- **Expected:** COMPLETED with a DOCS_DIFF and repository suite NOT_RUN with a reason
- **Verdict:** PASS — DOCS_DIFF; suite=NOT_RUN (required test dependency is unavailable inside the network-disabled sandbox: No module named 'railroad'. Installing it w)

## Retrieval

- **Status:** `COMPLETE`
- **Files:** 192 examined of 192 eligible (293 tracked)
- **Evidence records:** 8
- **Summary:** Retrieval is COMPLETE: examined 192 of 192 eligible file(s) from 293 tracked file(s), read 2085671 byte(s), and retained 28 matching file(s). No retrieval limit was reached.


## Artifact

- **Kind:** `DOCS_DIFF`
- **Paths:** `README.rst`
- **Patch lines:** 23

## Documents

- `CONTRIBUTION_PLAN.md` (CONTRIBUTION_PLAN)

## Receipt

| Check | Status | Detail |
|---|---|---|
| `patch-path-policy` | `PASSED` |  |
| `patch-applies-on-pinned-commit` | `PASSED` |  |
| `sandbox-egress-isolation` | `PASSED` | every egress attempt from inside the sandbox was refused |
| `repository-test-suite` | `NOT_RUN` | required test dependency is unavailable inside the network-disabled sandbox: No module named 'railroad'. Installing it would require network access, which the sandbox denies. |

## Comparison

- **Outcome:** `BASELINE_INCOMPLETE`
- **Baseline:** `NOT_RUN`
- **Post-patch:** `NOT_RUN`
- **Interpretation:** the baseline check did not run, so post-patch results alone do not establish issue resolution

### Baseline output tail

```
==================================== ERRORS ====================================
____________________ ERROR collecting tests/test_diagram.py ____________________
ImportError while importing test module '/tmp/repomate-verify-vbj3jl3m/baseline/tests/test_diagram.py'.
Hint: make sure your test modules/packages have valid Python names.
Traceback:
/usr/lib/python3.14/importlib/__init__.py:88: in import_module
    return _bootstrap._gcd_import(name[level:], package, level)
           ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
tests/test_diagram.py:10: in <module>
    from pyparsing.diagram import to_railroad, railroad_to_html, NamedDiagram, AnnotatedItem
pyparsing/diagram/__init__.py:5: in <module>
    import railroad
E   ModuleNotFoundError: No module named 'railroad'
=========================== short test summary info ============================
ERROR tests/test_diagram.py
!!!!!!!!!!!!!!!!!!!! Interrupted: 1 error during collection !!!!!!!!!!!!!!!!!!!!
1 error in 1.12s
```

### Post-patch output tail

```
==================================== ERRORS ====================================
____________________ ERROR collecting tests/test_diagram.py ____________________
ImportError while importing test module '/tmp/repomate-verify-vbj3jl3m/patched/tests/test_diagram.py'.
Hint: make sure your test modules/packages have valid Python names.
Traceback:
/usr/lib/python3.14/importlib/__init__.py:88: in import_module
    return _bootstrap._gcd_import(name[level:], package, level)
           ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
tests/test_diagram.py:10: in <module>
    from pyparsing.diagram import to_railroad, railroad_to_html, NamedDiagram, AnnotatedItem
pyparsing/diagram/__init__.py:5: in <module>
    import railroad
E   ModuleNotFoundError: No module named 'railroad'
=========================== short test summary info ============================
ERROR tests/test_diagram.py
!!!!!!!!!!!!!!!!!!!! Interrupted: 1 error during collection !!!!!!!!!!!!!!!!!!!!
1 error in 1.66s
```

## Provenance

- Case workspace: `var/eval-real/cases/unavailable_toolchain_pyparsing`
- Elapsed: 11.95s
- Sandbox backend: `bwrap`
- Planner requested: `scripted`

## Notes

The sandbox detects that the pyparsing test suite needs the 'railroad' package, which is unavailable and cannot be installed without network access. The per-file retrieval byte cap is raised for this case so evidence collection reaches verification; it is not the scenario under test.
