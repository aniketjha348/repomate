"""Evidence-retrieval budgets and the report that proves what was covered.

Retrieval is bounded in files, bytes per file, total bytes, matching search
results and wall-clock time. Reaching any limit makes the report ``PARTIAL``
and records what was left unexamined; a partial scan is never described as a
complete repository analysis.
"""

from __future__ import annotations

from pydantic import BaseModel, Field, model_validator

from repomate_core.contracts.enums import RetrievalLimit, RetrievalStatus


class RetrievalLimits(BaseModel):
    """Hard caps for one evidence-retrieval pass."""

    max_files: int = Field(default=2000, ge=1)
    max_bytes_per_file: int = Field(default=200_000, ge=1)
    max_total_bytes: int = Field(default=32_000_000, ge=1)
    max_search_results: int = Field(default=200, ge=1)
    max_seconds: float = Field(default=30.0, gt=0)


class RetrievalLimitHit(BaseModel):
    """One exhausted budget and the work it left behind."""

    limit: RetrievalLimit
    allowed: int | float = Field(ge=0)
    observed: int | float = Field(ge=0)
    # Must state what was not examined; consumers render this verbatim.
    remaining_work: str = Field(min_length=1)


class RetrievalReport(BaseModel):
    """Deterministic account of the repository scope retrieval examined."""

    status: RetrievalStatus
    limits: RetrievalLimits
    files_total: int = Field(ge=0)
    files_eligible: int = Field(ge=0)
    files_examined: int = Field(ge=0)
    bytes_read: int = Field(ge=0)
    search_results: int = Field(ge=0)
    evidence_records: int = Field(ge=0)
    elapsed_ms: int = Field(ge=0)
    limit_hits: list[RetrievalLimitHit] = []
    summary: str = Field(min_length=1)

    @model_validator(mode="after")
    def _partial_state_is_explicit(self) -> "RetrievalReport":
        if self.files_examined > self.files_eligible:
            raise ValueError("examined files cannot exceed eligible files")
        if self.status is RetrievalStatus.PARTIAL:
            if not self.limit_hits:
                raise ValueError("a PARTIAL retrieval must record at least one limit hit")
            if "partial" not in self.summary.lower():
                raise ValueError("a PARTIAL retrieval summary must say the analysis is partial")
        elif self.limit_hits:
            raise ValueError("a COMPLETE retrieval cannot record limit hits")
        return self
