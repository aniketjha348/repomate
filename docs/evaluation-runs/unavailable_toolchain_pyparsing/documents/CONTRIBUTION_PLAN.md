# Contribution Plan

- **Repository:** `pyparsing/pyparsing`
- **Pinned commit:** `810199f89bf916590426e1c5cb3d612584f11a2f`
- **Planner:** `scripted-eval-v1`
- **Task type:** `DOCUMENTATION`
- **Run status:** `COMPLETED`
- **License:** `RECOGNIZED` (MIT)

## Task

Document the original_text_for helper in the README.

## Summary

Add a focused documentation section to README.rst.

## Planned changes

| Path | Change | Rationale |
|---|---|---|
| `README.rst` | MODIFY | the requested behavior belongs with the existing documentation |

## Acceptance criteria

- the new section is present and readable in the rendered file

## Evidence consulted

- `ev1` — `docs/HowToUsePyparsing.rst:1238-1249` — matches task keywords: original_text_for, helper

  ```
  .. _originalTextFor:
  
  - ``original_text_for(expr)`` - helper function to preserve the originally parsed text, regardless of any
    token processing or conversion done by the contained expression.  For instance, the following expression::
  
          full_name = Word(alphas) + Word(alphas)
  
    will return the parse of "John Smith" as ['John', 'Smith'].  In some applications, the actual name as it
    was given in the input string is what is desired.  To do this, use ``original_text_for``::
  
          full_name = original_text_for(Word(alphas) + Word(alphas))
  ```
- `ev2` — `docs/pyparsing_classes.md:206-212` — matches task keywords: original_text_for, helper

  ```
  Contains `pyparsing_unicode`, which provides `unicode_set` definitions for various languages and character sets (Latin, Greek, Cyrillic, CJK, etc.).
  
  ### `helpers.py`
  Offers high-level helper functions and classes for constructing complex parsers, such as `infix_notation`, `nested_expr`, `delimited_list`, and `original_text_for`.
  
  ### `actions.py`
  Provides useful parse actions and decorators, such as `replace_with`, `remove_quotes`, and `with_attribute`.
  ```
- `ev3` — `docs/whats_new_in_3_0_0.rst:172-183` — matches task keywords: helper

  ```
  pp.enable_diag(pp.Diagnostics.warn_multiple_tokens_in_named_alternation)
  
  - ``pyparsing.enable_all_warnings()`` is another helper that sets
    all "warn*" diagnostics to ``True``::
  
          pp.enable_all_warnings()
  
  - added support for calling ``enable_all_warnings()`` if warnings are enabled
    using the Python ``-W`` switch, or setting a non-empty value to the environment
    variable ``PYPARSINGENABLEALLWARNINGS``. (If using ``-Wd`` for testing, but
    wishing to disable pyparsing warnings, add ``-Wi:::pyparsing``.)
  ```
- `ev4` — `pyparsing/helpers.py:25-36` — matches task keywords: helper

  ```
  #
  # global helpers
  #
  def counted_array(
      expr: ParserElement, int_expr: typing.Optional[ParserElement] = None, **kwargs
  ) -> ParserElement:
      """Helper to define a counted list of expressions.
  
      This helper defines a pattern of the form::
  
          integer expr expr expr...
  ```
- `ev5` — `tests/test_pre_pep8_deprecation_warnings.py:286-297` — matches task keywords: original_text_for

  ```
  def test_original_text_for_asString_kwarg_emits_DeprecationWarning():
      # Using original_text_for with deprecated 'asString' kwarg
      inner = Word(alphas) + "," + Word(alphas)
      with pytest.warns(DeprecationWarning, match="'asString' argument is deprecated, use 'as_string'"):
          expr = original_text_for(inner, asString=False)
          res = expr.parse_string("ab,cd")
          # Returns original matched text as sole token
          assert res[0] == "ab,cd"
  ```
- `ev6` — `tests/test_unit.py:9957-9968` — matches task keywords: original_text_for

  ```
  with self.assertDoesNotWarn(
                  msg=f"raised {pp.Diagnostics.warn_ungrouped_named_tokens_in_collection}"
                  f" warning when warn on ungrouped named tokens was suppressed (original_text_for)"
              ):
                  pp.original_text_for(pp.Word("ABC")[...])("words")
  
      def testWarnNameSetOnEmptyForward(self):
          """
          - warn_name_set_on_empty_Forward - flag to enable warnings when a Forward is defined
            with a results name, but has no contents defined (default=False)
          """
  ```
- `ev7` — `pyparsing/__init__.py:150-161` — matches task keywords: helper

  ```
  from .core import *
  from .core import _builtin_exprs as core_builtin_exprs
  from .helpers import *
  from .helpers import _builtin_exprs as helper_builtin_exprs
  
  from .unicode import unicode_set, UnicodeRangeList, pyparsing_unicode as unicode
  from .testing import pyparsing_test as testing
  from .common import (
      pyparsing_common as common,
      _builtin_exprs as common_builtin_exprs,
  )
  from importlib import resources
  ```
- `ev8` — `examples/tiny/docs/transcript_2_tiny_interpreter.md:273-284` — matches task keywords: helper

  ```
  - In `eval_expr`, when encountering a `ParseResults` with `type == 'func_call'`, evaluate arguments left-to-right and delegate to a new `engine.call_function(name, args)` method. *
      - Implement `call_function(name, args)` to look up the function, push a new frame, bind parameters by declaring them with their declared types and the coerced argument values, execute the body statements one by one (building each as a `TinyNode` and calling `execute(engine)`), return on `ReturnStmtNode` or any non-`None` result, and finally pop the frame. If no explicit return occurs, return the default value fo…
  ```

## Grounding

- Resolved citations: 1 of 1
- `hypothesis` — Add a focused documentation section to README.rst.
- `hypothesis` — the new section is present and readable in the rendered file
- Warning `CLAIM_NOT_SUPPORTED_BY_EVIDENCE`: claim cites 'ev1' (docs/HowToUsePyparsing.rst), but that evidence shares no distinctive vocabulary with the claim

## Honest status

The selected checks do not establish a resolution. Read the comparison and the receipt's reasons before relying on this artifact.

<!-- Generated by RepoMate from persisted run data. -->
