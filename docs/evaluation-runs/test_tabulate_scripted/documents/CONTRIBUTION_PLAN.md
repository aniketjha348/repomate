# Contribution Plan

- **Repository:** `astanin/python-tabulate`
- **Pinned commit:** `268615a5c27dc40e5c22454c07b44d5c50410da0`
- **Planner:** `scripted-eval-v1`
- **Task type:** `TEST`
- **Run status:** `COMPLETED`
- **License:** `RECOGNIZED` (MIT)

## Task

Add a regression test for the simple grid output in the test suite.

## Summary

Add a deterministic regression test for simple grid rendering.

## Planned changes

| Path | Change | Rationale |
|---|---|---|
| `test/test_grid_contract.py` | CREATE | cover the public table rendering contract |

## Acceptance criteria

- the new test passes against the pinned snapshot

## Evidence consulted

- `ev1` — `test/test_output.py:2694-2705` — matches task keywords: test, output

  ```
  def test_latex_raw():
      "Output: raw latex with headers"
      raw_test_table_headers = list(_test_table_headers)
      raw_test_table_headers[-1] += " ($N_0$)"
      raw_test_table = list(map(list, _test_table))
      raw_test_table[0][0] += "$_1$"
      raw_test_table[1][0] = "\\emph{" + raw_test_table[1][0] + "}"
      print(raw_test_table)
      result = tabulate(raw_test_table, raw_test_table_headers, tablefmt="latex_raw")
      expected = "\n".join(
  ```
- `ev2` — `test/test_regression.py:6-17` — matches task keywords: regression, test

  ```
  def test_ansi_color_in_table_cells():
      "Regression: ANSI color in table cells (issue #5)."
      colortable = [("test", "\x1b[31mtest\x1b[0m", "\x1b[32mtest\x1b[0m")]
      colorlessheaders = ("test", "test", "test")
      formatted = tabulate(colortable, colorlessheaders, "pipe")
      expected = "\n".join(
          [
              "| test   | test   | test   |",
              "|:-------|:-------|:-------|",
              "| test   | \x1b[31mtest\x1b[0m   | \x1b[32mtest\x1b[0m   |",
  ```
- `ev3` — `README.md:173-184` — matches task keywords: simple, grid

  ```
  -   "simple"
  -   "github"
  -   "grid"
  -   "simple\_grid"
  -   "rounded\_grid"
  -   "heavy\_grid"
  -   "mixed\_grid"
  -   "double\_grid"
  -   "fancy\_grid"
  -   "outline"
  -   "simple\_outline"
  -   "rounded\_outline"
  ```
- `ev4` — `test/test_cli.py:372-383` — matches task keywords: test, simple, grid, output

  ```
  input_file.write(sample_input())
              input_file.flush()
              run_main_in_process(["-o", output_file.name, input_file.name])
              output_file.seek(0)
              out = output_file.file.read()
              assert_equal(out.splitlines(), SAMPLE_SIMPLE_FORMAT.splitlines())
  
  
  def test_inprocess_jsonl_from_stdin():
      """In-process: JSONL input from stdin, grid format"""
      out = run_main_in_process(["-r", "jsonl", "-f", "grid"], input_text=SAMPLE_INPUT_JSONL)
      assert_equal(out.splitlines(), SAMPLE_GRID_FORMAT.splitlines())
  ```
- `ev5` — `test/test_textwrapper.py:9-20` — matches task keywords: regression, test

  ```
  def test_wrap_multiword_non_wide():
      """TextWrapper: non-wide character regression tests"""
      data = "this is a test string for regression splitting"
      for width in range(1, len(data)):
          orig = OTW(width=width)
          cust = CTW(width=width)
  
          assert [line.rstrip() for line in orig.wrap(data)] == [
              line.rstrip() for line in cust.wrap(data)
          ], f"Failure on non-wide char multiword regression check for width {width}"
  ```
- `ev6` — `tabulate/__init__.py:720-731` — matches task keywords: simple, grid

  ```
  multiline_formats = {
      "plain": "plain",
      "simple": "simple",
      "grid": "grid",
      "simple_grid": "simple_grid",
      "rounded_grid": "rounded_grid",
      "heavy_grid": "heavy_grid",
      "mixed_grid": "mixed_grid",
      "double_grid": "double_grid",
      "fancy_grid": "fancy_grid",
      "colon_grid": "colon_grid",
      "pipe": "pipe",
  ```
- `ev7` — `test/test_api.py:61-67` — matches task keywords: test, simple

  ```
  def test_simple_separated_format_signature():
      "API: simple_separated_format() type signature is unchanged"
      assert type(simple_separated_format) is type(lambda: None)
      expected_sig = [("separator", _empty)]
      _check_signature(simple_separated_format, expected_sig)
  ```
- `ev8` — `test/test_grapheme_clusters.py:21-32` — matches task keywords: test

  ```
  requires_wcwidth = pytest.mark.skipif(not HAS_WCWIDTH, reason="requires wcwidth")
  
  requires_wcwidth_030 = pytest.mark.skipif(not HAS_WCWIDTH_030, reason="requires wcwidth >= 0.3.0")
  
  requires_wcwidth_width = pytest.mark.skipif(
      not HAS_WCWIDTH_WIDTH, reason="requires wcwidth with width() API"
  )
  
  
  class TestGraphemeClusterWidth:
      """Tests for correct width calculation of grapheme clusters."""
  ```

## Grounding

- Resolved citations: 1 of 1
- `hypothesis` — Add a deterministic regression test for simple grid rendering.
- `hypothesis` — the new test passes against the pinned snapshot
- Warning `CLAIM_NOT_SUPPORTED_BY_EVIDENCE`: claim cites 'ev1' (test/test_output.py), but that evidence shares no distinctive vocabulary with the claim

## Honest status

The selected checks show no regression; they do not prove the issue was fixed.

<!-- Generated by RepoMate from persisted run data. -->
