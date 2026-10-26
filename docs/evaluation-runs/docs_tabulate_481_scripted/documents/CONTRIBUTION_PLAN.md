# Contribution Plan

- **Repository:** `astanin/python-tabulate`
- **Pinned commit:** `268615a5c27dc40e5c22454c07b44d5c50410da0`
- **Planner:** `scripted-eval-v1`
- **Task type:** `DOCUMENTATION`
- **Run status:** `COMPLETED`
- **License:** `RECOGNIZED` (MIT)

## Task

README library-only installation option may no longer work with current packaging

The README documents setting `TABULATE_INSTALL=lib-only` when installing `tabulate` so that only the Python library is installed. It gives commands for Unix-like systems and Windows.

However, the repository's current `pyproject.toml` uses `flit_scm:buildapi` and declares a console entry point unconditionally:

```toml
[project.scripts]
tabulate = "tabulate.cli:_main"
```

I could not find a corresponding setting in the current packaging configuration that uses `TABULATE_INSTALL` to disable this entry point. The README option may be left over from a previous build system.

Relevant files:

- https://github.com/astanin/python-tabulate/blob/master/README.md
- https://github.com/astanin/python-tabulate/blob/master/pyproject.toml

## Expected behavior

Using the documented library-only installation option should omit the `tabulate` executable, or the README should clarify that the option is no longer supported.

## Suggested verification

In a fresh virtual environment, compare two installs built from the current source: one with the `TABULATE_INSTALL=lib-only` environment variable and one without it. Then inspect the generated console entry point, such as in the environment's `bin` or `Scripts` directory. This would confirm whether the environment variable changes what gets installed.

## Suggested improvement

If the setting is no longer supported, remove the library-only installation examples or explain the behavior supported by the current build system. If it is supported, it would help to document where the conditional behavior is implemented.

## Scope

This report is based on a comparison of the README and the current packaging configuration. I have not run a clean installation from the current repository, so I am reporting a documentation inconsistency to verify rather than a confirmed installation failure.

## Summary

Add a focused documentation section to README.md.

## Planned changes

| Path | Change | Rationale |
|---|---|---|
| `README.md` | MODIFY | the requested behavior belongs with the existing documentation |

## Acceptance criteria

- the new section is present and readable in the rendered file

## Evidence consulted

- `ev1` — `issue#481` — the GitHub issue this contribution addresses

  ```
  README library-only installation option may no longer work with current packaging
  
  The README documents setting `TABULATE_INSTALL=lib-only` when installing `tabulate` so that only the Python library is installed. It gives commands for Unix-like systems and Windows.
  
  However, the repository's current `pyproject.toml` uses `flit_scm:buildapi` and declares a console entry point unconditionally:
  
  ```toml
  [project.scripts]
  tabulate = "tabulate.cli:_main"
  ```
  
  I could not find a corresponding setting in the current packaging configuration that uses `TABULATE_INSTALL` to disable this entry point. The…
  ```
- `ev2` — `README.md:26-37` — matches task keywords: installation, current, installing

  ```
  The command line utility will be installed as `tabulate` to `bin` on
  Linux (e.g. `/usr/bin`); or as `tabulate.exe` to `Scripts` in your
  Python installation on Windows (e.g. `C:\Python39\Scripts\tabulate.exe`).
  
  You may consider installing the library only for the current user:
  
  ```shell
  pip install tabulate --user
  ```
  
  In this case the command line utility will be installed to
  `~/.local/bin/tabulate` on Linux and to
  ```
- `ev3` — `tabulate/__init__.py:268-279` — matches task keywords: option, current

  ```
  header_list = ['cols="' + (",".join(asciidoc_column_specifiers)) + '"']
  
          # generate the list of options (currently only "header")
          options_list = []
  
          if is_header:
              options_list.append("header")
  
          if options_list:
              options_list = ",".join(options_list)
              header_list.append(f'options="{options_list}"')
  ```
- `ev4` — `test/test_output.py:102-113` — matches task keywords: longer

  ```
  def test_plain_maxcolwidth_autowraps():
      "Output: maxcolwidth will result in autowrapping longer cells"
      table = [["hdr", "fold"], ["1", "very long data"]]
      expected = "\n".join(["  hdr  fold", "    1  very long", "       data"])
      result = tabulate(table, headers="firstrow", tablefmt="plain", maxcolwidths=[10, 10])
      assert_equal(expected, result)
  
  
  def test_plain_maxcolwidth_autowraps_with_sep():
      "Output: maxcolwidth will result in autowrapping longer cells and separating line"
      table = [
  ```
- `ev5` — `test/test_cli.py:180-191` — matches task keywords: option

  ```
  def test_script_header_option():
      """Command line utility: -1, --header option"""
      for option in ["-1", "--header"]:
          cmd = [sys.executable, "tabulate/cli.py", option]
          raw_table = sample_input(with_headers=True)
          out = run_and_capture_stdout(cmd, input=raw_table)
          expected = SAMPLE_SIMPLE_FORMAT_WITH_HEADERS
          print(out)
          print("got:     ", repr(out))
          print("expected:", repr(expected))
  ```
- `ev6` — `test/test_regression.py:586-597` — matches task keywords: option

  ```
  "Regression: asciidoc format output must not generate trailing whitespace (issue #408)"
      result = tabulate([["foo"]], headers=("longheader",), tablefmt="asciidoc")
      expected = '[cols="<14",options="header"]\n|====\n| longheader\n| foo\n|===='
      assert_equal(expected, result)
  
      result = tabulate([["longtext"]], headers=("bar",), tablefmt="asciidoc")
      expected = '[cols="<10",options="header"]\n|====\n| bar\n| longtext\n|===='
      assert_equal(expected, result)
  
  
  def test_github_escape_pipe_character():
      "Regression: github format must escape pipe character with a backslash (issu…
  ```
- `ev7` — `test/test_textwrapper.py:303-314` — matches task keywords: option

  ```
  def test_wrap_optional_bool_strs():
      """TextWrapper: Show that str bools and None can be wrapped without crashing"""
      data = [
          ["First Entry", "True"],
          ["Second Entry", None],
      ]
      headers = ["Title", "When"]
      result = tabulate(data, headers=headers, tablefmt="grid", maxcolwidths=[7, 5])
  
      expected = [
  ```
- `ev8` — `pyproject.toml:27-38` — matches task keywords: option

  ```
  Homepage = "https://github.com/astanin/python-tabulate"
  
  [project.optional-dependencies]
  widechars = ["wcwidth>=0.6.0"]
  
  [project.scripts]
  tabulate = "tabulate.cli:_main"
  
  [tool.flit.sdist]
  include = ["CHANGELOG", "test/", "tox.ini"]
  
  [tool.setuptools_scm]
  ```

## Grounding

- Resolved citations: 0 of 1
- Unresolved citation ids: `ev1`
- `hypothesis` — Add a focused documentation section to README.md.
- `hypothesis` — the new section is present and readable in the rendered file
- Warning `EVIDENCE_PATH_MISSING`: evidence 'ev1' cites 'issue#481', which is not in the pinned snapshot

## Honest status

The selected checks show no regression; they do not prove the issue was fixed.

<!-- Generated by RepoMate from persisted run data. -->
