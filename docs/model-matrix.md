# Model Matrix — Real Issue Run

Issue: https://github.com/psf/black/issues/2365 (open, MIT-licensed repository psf/black)
Generated 2026-10-25T19:09:21.958299+00:00 by `scripts/model_matrix.py`.

| Model | Status | Task type | Planned file | Patch lines | Patch checks | Suite | Time |
|-------|--------|-----------|--------------|-------------|-------------|-------|------|
| `deepseek-v4.1` | COMPLETED | DOCUMENTATION | `docs/usage_and_configuration/the_basics.md` | 27 | patch=PASSED,patch=PASSED | FAILED | 20.1s |
| `deepseek-v4-flash` | FAILED · MODEL_ERROR | - | `-` | 0 | - | - | 22.3s |
| `glm-5.3-flash` | COMPLETED | DOCUMENTATION | `docs/usage_and_configuration/the_basics.md` | 27 | patch=PASSED,patch=PASSED | FAILED | 51.6s |
| `beam-1.0` | NEED_MORE_INFO | DOCUMENTATION | `-` | 0 | - | - | 31.2s |
| `nemotron-3.5-super-vl` | COMPLETED | DOCUMENTATION | `docs/usage_and_configuration/the_basics.md` | 27 | patch=PASSED,patch=PASSED | FAILED | 25.0s |

## Plan summaries

- **deepseek-v4.1** (model:vyce/deepseek-v4.1): Document the `# fmt: off` / `# fmt: on` directives in the Usage section of the Black documentation, based on user feedback that finding this information requires too many clicks and is currently burie
- **deepseek-v4-flash** (model:vyce/deepseek-v4-flash): —
- **glm-5.3-flash** (model:vyce/glm-5.3-flash): Issue #2365 asks that `# fmt: off` be documented under Usage and that the docs site be flattened. At snapshot commit 80db630a the first ask is already largely satisfied: docs/usage_and_configuration/t
- **beam-1.0** (model:vyce/beam-1.0): Make Black's pragma documentation (`# fmt: off` / `# fmt: on`, `# fmt: skip`, and YAPF aliases) easy to find directly under Usage, and investigate flattening the docs navigation. The supplied evidence
- **nemotron-3.5-super-vl** (model:vyce/nemotron-3.5-super-vl): Add a clear, example-driven `# fmt: off` / `# fmt: on` usage section to docs/usage_and_configuration/the_basics.md to improve discoverability per issue#2365.

The repository test suite fails for every model in this bare environment
(black's dependencies are not installed) — an honest FAILED with the
captured output, per the verification contract.

## Interpretation

> The `model:vyce/*` planner labels below are the historical records of
> these runs; the adapter has since been renamed `OpenAIProvider`
> (`model:openai/*` in new runs) because the gateway speaks the standard
> OpenAI chat-completions protocol.

- **deepseek-v4.1** is the recommended default: fastest correct run and
  the most precise plan.
- **deepseek-v4-flash** failed schema adherence on this prompt: it
  returned `planned_changes` as an array of plain strings instead of
  objects (diagnosed with a direct gateway probe — HTTP 200, valid JSON,
  wrong shape). The planner now tolerates *partial* compliance and
  raises a typed `MODEL_ERROR` with a precise reason when a model
  produces zero usable entries (see
  tests/unit/test_model_planner_coercion.py).
- **beam-1.0** legitimately returned `need_more_info`: its own reasoning
  judged the supplied evidence insufficient — the honest-deferral path
  working as designed, not a failure.
- **glm-5.3-flash** noted in its plan that the issue's first ask is
  already partly satisfied at the pinned commit — evidence-grounded
  nuance worth surfacing in a future "already-done" detection.

