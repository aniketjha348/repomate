"""The run record — one row of the system of record.

Phase 5 moves persistence to PostgreSQL; the shape stays.
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field

from repomate_core.contracts._time import utcnow
from repomate_core.contracts.artifact import ContributionArtifact
from repomate_core.contracts.evidence import EvidenceRecord
from repomate_core.contracts.enums import RunStatus
from repomate_core.contracts.input import GitHubIssue, RepositoryInput
from repomate_core.contracts.plan import ContributionPlan
from repomate_core.contracts.run_event import RunError, RunEvent
from repomate_core.contracts.snapshot import RepositorySnapshot
from repomate_core.contracts.verification import VerificationReceipt


class RunRecord(BaseModel):
    run_id: str
    status: RunStatus = RunStatus.PENDING
    input: RepositoryInput
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)
    snapshot: RepositorySnapshot | None = None
    issue: GitHubIssue | None = None
    evidence: list[EvidenceRecord] = []
    plan: ContributionPlan | None = None
    artifact: ContributionArtifact | None = None
    receipt: VerificationReceipt | None = None
    events: list[RunEvent] = []
    error: RunError | None = None
    planner: str = ""
    workspace_kept: bool = False

    @property
    def is_terminal(self) -> bool:
        return self.status in {
            RunStatus.COMPLETED,
            RunStatus.NEED_MORE_INFO,
            RunStatus.FAILED,
            RunStatus.CANCELLED,
        }
