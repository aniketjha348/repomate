"""Typed contracts shared by every RepoMate service (Phase 1 deliverable).

These models are the stable seam between the API layer, the background
worker and the core engine — anything crossing a process boundary (HTTP
responses, run records on disk, SSE events) is expressed here. Split into
small modules; this package re-exports the full surface as one namespace.
"""

from repomate_core.contracts._time import new_run_id, utcnow
from repomate_core.contracts.artifact import ArtifactDocument, ContributionArtifact
from repomate_core.contracts.evidence import EvidenceRecord
from repomate_core.contracts.enums import (
    ArtifactKind,
    ComparisonOutcome,
    ErrorCode,
    EvidenceKind,
    LicenseStatus,
    RetrievalLimit,
    RetrievalStatus,
    RunStatus,
    StageName,
    TaskSource,
    TaskType,
    VerificationStatus,
)
from repomate_core.contracts.fair_use import (
    ModelBudgetLimits,
    ModelBudgetReport,
)
from repomate_core.contracts.grounding import (
    GroundedClaim,
    GroundingReport,
    GroundingWarning,
    SupportStatus,
)
from repomate_core.contracts.input import GitHubIssue, RepositoryInput
from repomate_core.contracts.insights import (
    KeyPath,
    Orientation,
    RelevantTest,
    TestGuidance,
)
from repomate_core.contracts.plan import (
    ContributionPlan,
    PlannedChange,
    ProposedClaim,
    ProposedEdit,
)
from repomate_core.contracts.retrieval import (
    RetrievalLimitHit,
    RetrievalLimits,
    RetrievalReport,
)
from repomate_core.contracts.run_event import RunError, RunEvent
from repomate_core.contracts.run_record import RunRecord
from repomate_core.contracts.snapshot import (
    EntryPoint,
    LicenseInfo,
    RepositorySnapshot,
)
from repomate_core.contracts.tools import (
    ToolCall,
    ToolCallRecord,
    ToolLoopLimit,
    ToolLoopLimitHit,
    ToolLoopLimits,
    ToolLoopReport,
    ToolLoopStatus,
    ToolName,
)
from repomate_core.contracts.verification import (
    SandboxPolicyRecord,
    VerificationCheck,
    VerificationComparison,
    VerificationReceipt,
    VerificationRunRecord,
    classify_comparison_outcome,
    comparison_interpretation,
    resolution_statement,
)

__all__ = [
    "ArtifactDocument",
    "ArtifactKind",
    "ComparisonOutcome",
    "ContributionArtifact",
    "ContributionPlan",
    "EntryPoint",
    "ErrorCode",
    "EvidenceKind",
    "EvidenceRecord",
    "GitHubIssue",
    "GroundedClaim",
    "GroundingReport",
    "GroundingWarning",
    "KeyPath",
    "LicenseInfo",
    "LicenseStatus",
    "ModelBudgetLimits",
    "ModelBudgetReport",
    "PlannedChange",
    "ProposedClaim",
    "ProposedEdit",
    "Orientation",
    "RelevantTest",
    "RepositoryInput",
    "RepositorySnapshot",
    "RetrievalLimit",
    "RetrievalLimitHit",
    "RetrievalLimits",
    "RetrievalReport",
    "RetrievalStatus",
    "RunError",
    "RunEvent",
    "RunRecord",
    "RunStatus",
    "SandboxPolicyRecord",
    "StageName",
    "SupportStatus",
    "TaskSource",
    "TaskType",
    "TestGuidance",
    "ToolCall",
    "ToolCallRecord",
    "ToolLoopLimit",
    "ToolLoopLimitHit",
    "ToolLoopLimits",
    "ToolLoopReport",
    "ToolLoopStatus",
    "ToolName",
    "VerificationCheck",
    "VerificationComparison",
    "VerificationReceipt",
    "VerificationRunRecord",
    "VerificationStatus",
    "classify_comparison_outcome",
    "comparison_interpretation",
    "new_run_id",
    "resolution_statement",
    "utcnow",
]
