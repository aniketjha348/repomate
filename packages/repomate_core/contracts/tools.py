"""Typed tool calls and the report produced by the bounded retrieval loop.

The model may ask for ``search_text``, ``read_file`` or ``inspect_manifest``.
Every file item it receives is re-validated against the pinned workspace
before it becomes evidence; the loop itself is capped by tool calls, total
bytes and wall-clock time. A global cap hit is reported as ``PARTIAL`` with
the work that was left unexamined.
"""

from __future__ import annotations

import enum
from typing import Literal

from pydantic import BaseModel, Field, model_validator


class ToolName(str, enum.Enum):
    SEARCH_TEXT = "search_text"
    READ_FILE = "read_file"
    INSPECT_MANIFEST = "inspect_manifest"
    DONE = "done"


class ToolLoopStatus(str, enum.Enum):
    COMPLETE = "COMPLETE"
    PARTIAL = "PARTIAL"


class ToolLoopLimit(str, enum.Enum):
    MAX_TOOL_CALLS = "MAX_TOOL_CALLS"
    MAX_TOTAL_BYTES = "MAX_TOTAL_BYTES"
    MAX_SECONDS = "MAX_SECONDS"


class ToolCall(BaseModel):
    """One typed request from the model.

    Unknown extra keys are ignored rather than rejecting an otherwise valid
    call: gateways sometimes add explanatory fields. Fields that are present
    must still be well-typed.
    """

    tool: ToolName
    query: str = Field(default="", max_length=300)
    path: str = Field(default="", max_length=500)
    start_line: int | None = Field(default=None, ge=1)
    end_line: int | None = Field(default=None, ge=1)
    max_results: int | None = Field(default=None, ge=1, le=50)


class ToolLoopLimits(BaseModel):
    """Hard caps for one bounded tool loop."""

    max_tool_calls: int = Field(default=8, ge=1)
    max_total_bytes: int = Field(default=4_000_000, ge=1)
    max_seconds: float = Field(default=180.0, gt=0)
    max_results_per_search: int = Field(default=20, ge=1, le=100)


class ToolCallRecord(BaseModel):
    """Audit row for one model tool request."""

    index: int = Field(ge=1)
    tool: ToolName
    target: str = ""
    status: Literal["OK", "REJECTED", "ERROR"]
    detail: str = ""
    bytes_read: int = Field(default=0, ge=0)
    evidence_paths: list[str] = []


class ToolLoopLimitHit(BaseModel):
    """One exhausted global tool budget and the work it left behind."""

    limit: ToolLoopLimit
    allowed: int | float = Field(ge=0)
    observed: int | float = Field(ge=0)
    remaining_work: str = Field(min_length=1)


class ToolLoopReport(BaseModel):
    """Deterministic account of the supplementary model-driven retrieval."""

    status: ToolLoopStatus
    limits: ToolLoopLimits
    model_calls: int = Field(default=0, ge=0)
    tool_calls: int = Field(default=0, ge=0)
    bytes_read: int = Field(default=0, ge=0)
    records_added: int = Field(default=0, ge=0)
    rejected_items: int = Field(default=0, ge=0)
    calls: list[ToolCallRecord] = []
    limit_hits: list[ToolLoopLimitHit] = []
    stop_reason: str = Field(default="", max_length=200)
    summary: str = Field(min_length=1)

    @model_validator(mode="after")
    def _partial_state_is_explicit(self) -> "ToolLoopReport":
        if self.status is ToolLoopStatus.PARTIAL:
            if not self.limit_hits:
                raise ValueError("a PARTIAL tool loop must record at least one limit hit")
            if "partial" not in self.summary.lower():
                raise ValueError("a PARTIAL tool loop summary must say the retrieval is partial")
        elif self.limit_hits:
            raise ValueError("a COMPLETE tool loop cannot record limit hits")
        return self
