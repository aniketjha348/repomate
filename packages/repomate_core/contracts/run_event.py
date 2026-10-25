"""Progress events and typed run errors."""

from __future__ import annotations

from datetime import datetime
from typing import Literal, Optional

from pydantic import BaseModel, Field

from repomate_core.contracts._time import utcnow
from repomate_core.contracts.enums import ErrorCode, StageName


class RunEvent(BaseModel):
    seq: int
    stage: Optional[StageName] = None
    status: Literal["STARTED", "COMPLETED", "FAILED", "INFO"]
    message: str
    at: datetime = Field(default_factory=utcnow)


class RunError(BaseModel):
    code: ErrorCode
    message: str
    detail: str = ""
