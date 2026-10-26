"""Per-run model budget enforcement.

The budget must be checked before a call (so an exhausted run cannot spend)
and must account for reported usage as well as gateways that omit it.
"""

import pytest

from repomate_core.contracts import ModelBudgetLimits
from repomate_core.models import (
    ModelBudget,
    ModelBudgetExceeded,
    ModelResult,
)


def _result(prompt=None, completion=None, text="a" * 40) -> ModelResult:
    usage = None
    if prompt is not None:
        usage = {"prompt_tokens": prompt, "completion_tokens": completion}
    return ModelResult(text=text, provider="fake", model="fake-1", usage=usage)


def test_reported_usage_accumulates():
    budget = ModelBudget(ModelBudgetLimits(max_calls=5, max_tokens=1000))
    budget.start_call(estimated_prompt_tokens=10)
    budget.record_result(_result(30, 20))
    budget.start_call(estimated_prompt_tokens=10)
    budget.record_result(_result(40, 10))

    report = budget.report()
    assert report.calls == 2
    assert report.prompt_tokens == 70
    assert report.completion_tokens == 30
    assert report.total_tokens == 100
    assert report.usage_source == "reported"
    assert report.exhausted is False
    assert report.reason == ""


def test_call_cap_refuses_before_spending():
    budget = ModelBudget(ModelBudgetLimits(max_calls=1, max_tokens=10_000))
    budget.start_call()
    budget.record_result(_result(1, 1))

    with pytest.raises(ModelBudgetExceeded, match="call budget"):
        budget.start_call()

    assert budget.calls == 1
    report = budget.report()
    assert report.exhausted is True
    assert "1 of 1 calls" in report.reason


def test_token_cap_is_checked_before_the_next_call():
    budget = ModelBudget(ModelBudgetLimits(max_calls=10, max_tokens=100))
    budget.start_call(estimated_prompt_tokens=10)
    budget.record_result(_result(60, 30))  # 90 of 100

    with pytest.raises(ModelBudgetExceeded, match="token budget"):
        budget.start_call(estimated_prompt_tokens=10)

    assert budget.calls == 1
    assert budget.report().total_tokens == 90
    assert "90 of 100 tokens" in budget.report().reason


def test_missing_usage_is_estimated_and_labelled():
    budget = ModelBudget(ModelBudgetLimits(max_calls=5, max_tokens=10_000))
    budget.start_call(estimated_prompt_tokens=25)
    budget.record_result(_result(text="x" * 40))

    report = budget.report()
    assert report.usage_source == "estimated"
    assert report.prompt_tokens == 25
    assert report.completion_tokens == 10
    assert report.total_tokens == 35


def test_mixed_sources_are_reported_as_mixed():
    budget = ModelBudget(ModelBudgetLimits(max_calls=5, max_tokens=10_000))
    budget.start_call(estimated_prompt_tokens=5)
    budget.record_result(_result(10, 5))
    budget.start_call(estimated_prompt_tokens=5)
    budget.record_result(_result(text="y" * 20))

    report = budget.report()
    assert report.usage_source == "mixed"
    assert report.prompt_tokens == 15
    assert report.completion_tokens == 10


def test_report_totals_always_match_components():
    budget = ModelBudget()
    report = budget.report()
    assert report.total_tokens == report.prompt_tokens + report.completion_tokens
    assert report.usage_source == "none"
    assert report.exhausted is False
