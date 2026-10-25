"""A single piece of cited evidence backing a plan."""

from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, Field

from repomate_core.contracts.enums import EvidenceKind


class EvidenceRecord(BaseModel):
    id: str
    kind: EvidenceKind
    path: str
    start_line: Optional[int] = None
    end_line: Optional[int] = None
    snippet: str = Field(default="", max_length=4000)
    rationale: str
