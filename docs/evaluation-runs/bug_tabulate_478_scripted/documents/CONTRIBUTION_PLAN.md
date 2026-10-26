# Contribution Plan

- **Repository:** `astanin/python-tabulate`
- **Pinned commit:** `df8421880b41229b51edee238d87f689bf96e5b0`
- **Planner:** `scripted-eval-v1`
- **Task type:** `BUG_FIX`
- **Run status:** `COMPLETED`
- **License:** `RECOGNIZED` (MIT)

## Task

_CustomTextWrap produces lines wider than `width` after the #399 fix (032dc0d)

The fix for #399 (032dc0d, on `master`, not in a release yet) stops the infinite loop, but it also makes some lines wider than the requested width. Before that commit, the same inputs wrapped correctly.

### Minimal repro

```python
>>> import tabulate, wcwidth
>>> out = tabulate._CustomTextWrap(width=3).wrap("a 글글")
>>> out, [wcwidth.wcswidth(x) for x in out]
(['a 글', '글'], [4, 2])        # master @ 268615a: first line is 4 columns in a 3-column width
```

Before 032dc0d (and on PyPI 0.10.0): `['a ', '글', '글']`, which fits.

In a table:

```python
>>> print(tabulate.tabulate([["a 글글"]], maxcolwidths=[3], tablefmt="grid"))
+------+
| a 글 |
| 글   |
+------+
```

### Cause

In `_handle_long_word`:

```python
i = max(i, 2)
```

This forces at least one character onto the line even when `cur_line` already has content, so a wide character that doesn't fit in the remaining space gets squeezed onto a non-empty line. Forcing progress is only needed when the line is empty. Taking the character in that case still breaks the loop, and otherwise the chunk can move to the next line as before:

```python
if i == 1 and not cur_line and stripped_chunk:
    i = 2
```

### How I found it

I compared the pre-fix code and master on 6,910 random strings (a mix of ASCII, CJK, emoji, combining marks and ANSI codes, at widths 1/2/3/4/7). The pre-fix code hangs on 1,291 of them. Master fixes all of those hangs, but changes 201 outputs that previously terminated, and all 201 now have a line wider than `width`. With the guard above, every hang is fixed and none of the previously-terminating outputs change. The full `test/` suite passes, including the #399 test.

Happy to open a PR with this change and a regression test if that's useful.

## Summary

Only force two-character progress when the current line is empty, so a wide character cannot overflow a non-empty line.

## Planned changes

| Path | Change | Rationale |
|---|---|---|
| `tabulate/__init__.py` | MODIFY | issue #478 identifies the forced progress as the cause |

## Acceptance criteria

- _CustomTextWrap(width=3).wrap('a 글글') has no line wider than 3 columns

## Evidence consulted

- `ev1` — `issue#478` — the GitHub issue this contribution addresses

  ```
  _CustomTextWrap produces lines wider than `width` after the #399 fix (032dc0d)
  
  The fix for #399 (032dc0d, on `master`, not in a release yet) stops the infinite loop, but it also makes some lines wider than the requested width. Before that commit, the same inputs wrapped correctly.
  
  ### Minimal repro
  
  ```python
  >>> import tabulate, wcwidth
  >>> out = tabulate._CustomTextWrap(width=3).wrap("a 글글")
  >>> out, [wcwidth.wcswidth(x) for x in out]
  (['a 글', '글'], [4, 2])        # master @ 268615a: first line is 4 columns in a 3-column width
  ```
  
  Before 032dc0d (and on PyPI 0.10.0): `['a ', '글', '글']`, w…
  ```
- `ev2` — `README.md:1054-1065` — matches task keywords: lines, than, width, after

  ```
  Text is preferably wrapped on whitespaces and right after the hyphens in hyphenated words.
  
  break_long_words (default: True)  If true, then words longer than width will be broken in order to ensure that no lines are longer than width.
  If it is false, long words will not be broken, and some lines may be longer than width.
  (Long words will be put on a line by themselves, in order to minimize the amount by which width is exceeded.)
  
  break_on_hyphens (default: True) If true, wrapping will occur preferably on whitespaces and right after hyphens in compound words, as it is customary in English.
  If f…
  ```
- `ev3` — `tabulate/__init__.py:2561-2572` — matches task keywords: lines, width

  ```
  lines, padded_multiline_cells, padded_widths, colaligns, rowfmt, pad, rowalign=None
  ):
      colwidths = [w - 2 * pad for w in padded_widths]
      cells_lines = [c.splitlines() for c in padded_multiline_cells]
      nlines = max(map(len, cells_lines))  # number of lines in the row
      # vertically pad cells where some lines are missing
      # cells_lines = [
      #     (cl + [" " * w] * (nlines - len(cl))) for cl, w in zip(cells_lines, colwidths)
      # ]
  
      cells_lines = [
          _align_cell_veritically(cl, nlines, w, rowalign) for cl, w in zip(cells_lines, colwidths)
  ```
- `ev4` — `test/test_textwrapper.py:338-349` — matches task keywords: lines, than, width

  ```
  for width in [2, 3, 4, 5, 6]:
          wrapper = CTW(width=width)
          lines = wrapper.wrap(data)
          for line in lines:
              display_width = wcwidth.wcswidth(line)
              assert display_width <= width, (
                  f"Line {line!r} has display width {display_width} "
                  f"which exceeds requested column width {width}"
              )
  
  
  def test_wrap_wide_char_narrower_than_char_width():
  ```
- `ev5` — `test/test_cli.py:170-181` — matches task keywords: lines

  ```
  print("got:     ", repr(out))
              print("expected:", repr(expected))
              assert_equal(out.splitlines(), expected.splitlines())
              # check that the output was written to file
              output_file.seek(0)
              out = output_file.file.read()
              expected = SAMPLE_SIMPLE_FORMAT
              print("got:     ", repr(out))
              print("expected:", repr(expected))
              assert_equal(out.splitlines(), expected.splitlines())
  ```
- `ev6` — `test/test_issue_478_regression.py:1-9` — matches task keywords: customtextwrap, lines, width

  ```
  import wcwidth
  
  from tabulate import _CustomTextWrap
  
  
  def test_wrapped_wide_char_lines_fit_width():
      lines = _CustomTextWrap(width=3).wrap("a 글글")
      widths = [wcwidth.wcswidth(line) for line in lines]
      assert all(width <= 3 for width in widths), (lines, widths)
  ```
- `ev7` — `test/test_grapheme_clusters.py:10-21` — matches task keywords: width

  ```
  import wcwidth
  
      HAS_WCWIDTH = True
      HAS_WCWIDTH_030 = hasattr(wcwidth, "wrap")
      HAS_WCWIDTH_WIDTH = hasattr(wcwidth, "width")
  except ImportError:
      wcwidth = None
      HAS_WCWIDTH = False
      HAS_WCWIDTH_030 = False
      HAS_WCWIDTH_WIDTH = False
  
  requires_wcwidth = pytest.mark.skipif(not HAS_WCWIDTH, reason="requires wcwidth")
  ```
- `ev8` — `test/test_internal.py:77-88` — matches task keywords: lines, width

  ```
  def test_align_cell_veritically_one_line_only():
      "Internal: Aligning a single height cell is same regardless of alignment value"
      lines = ["one line"]
      column_width = 8
  
      top = T._align_cell_veritically(lines, 1, column_width, "top")
      center = T._align_cell_veritically(lines, 1, column_width, "center")
      bottom = T._align_cell_veritically(lines, 1, column_width, "bottom")
      none = T._align_cell_veritically(lines, 1, column_width, None)
  
      expected = ["one line"]
      assert top == center == bottom == none == expected
  ```

## Grounding

- Resolved citations: 0 of 1
- Unresolved citation ids: `ev1`
- `hypothesis` — Only force two-character progress when the current line is empty, so a wide character cannot overflow a non-empty line.
- `hypothesis` — _CustomTextWrap(width=3).wrap('a 글글') has no line wider than 3 columns
- Warning `EVIDENCE_PATH_MISSING`: evidence 'ev1' cites 'issue#478', which is not in the pinned snapshot

## Honest status

The selected checks improved consistently between the baseline and patched checkouts. This is not proof that the issue is fully resolved.

<!-- Generated by RepoMate from persisted run data. -->
