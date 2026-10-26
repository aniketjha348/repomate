"""Per-run model budgets and the usage report that proves enforcement.

A run may make at most ``max_calls`` model calls and consume at most
``max_tokens`` reported (or conservatively estimated) tokens. The budget is
enforced before every call and recorded after each result, so a runaway tool
loop or corrective retry cannot spend without bound.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, model_validator


class ModelBudgetLimits(BaseModel):
    """Hard caps for model usage in one run."""

    max_calls: int = Field(default=10, ge=1)
    max_tokens: int = Field(default=120_000, ge=1)


class ModelBudgetReport(BaseModel):
    """What the run actually spent against its model budget."""

    limits: ModelBudgetLimits
    calls: int = Field(default=0, ge=0)
    prompt_tokens: int = Field(default=0, ge=0)
    completion_tokens: int = Field(default=0, ge=0)
    total_tokens: int = Field(default=0, ge=0)
    # ``reported`` means the gateway supplied usage counts; ``estimated``
    # means token counts were derived from prompt/response length because the
    # gateway omitted them. The distinction is never hidden.
    usage_source: Literal["reported", "estimated", "mixed", "none"] = "none"
    exhausted: bool = False
    reason: str = ""

    @model_validator(mode="after")
    def _totals_are_consistent(self) -> "ModelBudgetReport":
        if self.total_tokens != self.prompt_tokens + self.completion_tokens:
            raise ValueError("total_tokens must equal prompt_tokens + completion_tokens")
        if self.exhausted and not self.reason:
            raise ValueError("an exhausted model budget must state the reason")
        return self
