"""Verification checks and the aggregated receipt.

Honesty contract: ``PASSED``/``FAILED`` may only originate from real
execution or deterministic evaluation; ``NOT_RUN`` requires a reason.
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field, model_validator

from repomate_core.contracts._time import utcnow
from repomate_core.contracts.enums import VerificationStatus


class VerificationCheck(BaseModel):
    name: str
    command: str | None = None
    status: VerificationStatus
    exit_code: int | None = None
    output_tail: str = Field(default="", max_length=2000)
    reason: str = ""

    @model_validator(mode="after")
    def _check_not_run_reason(self) -> "VerificationCheck":
        if self.status is VerificationStatus.NOT_RUN and not self.reason.strip():
            raise ValueError("NOT_RUN checks must carry an explicit reason")
        return self


class VerificationReceipt(BaseModel):
    checks: list[VerificationCheck]
    overall: VerificationStatus
    environment: str
    limitations: list[str] = []
    created_at: datetime = Field(default_factory=utcnow)
