"""The run record — one row of the system of record.

Phase 5 moves persistence to PostgreSQL; the shape stays.
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field

from repomate_core.contracts._time import utcnow
from repomate_core.contracts.artifact import ArtifactDocument, ContributionArtifact
from repomate_core.contracts.evidence import EvidenceRecord
from repomate_core.contracts.enums import RunStatus
from repomate_core.contracts.fair_use import ModelBudgetReport
from repomate_core.contracts.grounding import GroundingReport
from repomate_core.contracts.insights import Orientation, TestGuidance
from repomate_core.contracts.input import GitHubIssue, RepositoryInput
from repomate_core.contracts.plan import ContributionPlan
from repomate_core.contracts.retrieval import RetrievalReport
from repomate_core.contracts.run_event import RunError, RunEvent
from repomate_core.contracts.snapshot import RepositorySnapshot
from repomate_core.contracts.tools import ToolLoopReport
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
    # Scope of the retrieval pass: files/bytes/results examined, plus every
    # exhausted limit and the work it left unexamined. ``PARTIAL`` retrieval
    # makes the run ``PARTIAL``; a complete scan says so explicitly.
    retrieval: RetrievalReport | None = None
    orientation: Orientation | None = None
    test_guidance: TestGuidance | None = None
    # Supplementary, model-directed retrieval (bounded tool loop) and the
    # run's actual model spend against its per-run fair-use budget.
    tool_loop: ToolLoopReport | None = None
    model_usage: ModelBudgetReport | None = None
    plan: ContributionPlan | None = None
    # Claim-level grounding verdict for ``plan``: which citations resolved
    # against this run's evidence and which claims are hypotheses.
    grounding: GroundingReport | None = None
    artifact: ContributionArtifact | None = None
    # Non-diff downloadable outputs (CONTRIBUTION_PLAN.md, REPRO_CHECKLIST.md).
    # Persisted with the record so both stores and the artifact-list endpoint
    # expose the same stable snapshot.
    documents: list[ArtifactDocument] = []
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
            RunStatus.PARTIAL,
            RunStatus.FAILED,
            RunStatus.CANCELLED,
        }
