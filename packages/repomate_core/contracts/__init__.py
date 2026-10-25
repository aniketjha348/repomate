"""Typed contracts shared by every RepoMate service (Phase 1 deliverable).

These models are the stable seam between the API layer, the background
worker and the core engine — anything crossing a process boundary (HTTP
responses, run records on disk, SSE events) is expressed here. Split into
small modules; this package re-exports the full surface as one namespace.
"""

from repomate_core.contracts._time import new_run_id, utcnow
from repomate_core.contracts.artifact import ContributionArtifact
from repomate_core.contracts.evidence import EvidenceRecord
from repomate_core.contracts.enums import (
    ArtifactKind,
    ErrorCode,
    EvidenceKind,
    LicenseStatus,
    RunStatus,
    StageName,
    TaskSource,
    TaskType,
    VerificationStatus,
)
from repomate_core.contracts.input import GitHubIssue, RepositoryInput
from repomate_core.contracts.insights import (
    KeyPath,
    Orientation,
    RelevantTest,
    TestGuidance,
)
from repomate_core.contracts.plan import ContributionPlan, PlannedChange, ProposedEdit
from repomate_core.contracts.run_event import RunError, RunEvent
from repomate_core.contracts.run_record import RunRecord
from repomate_core.contracts.snapshot import (
    EntryPoint,
    LicenseInfo,
    RepositorySnapshot,
)
from repomate_core.contracts.verification import VerificationCheck, VerificationReceipt

__all__ = [
    "ArtifactKind",
    "ContributionArtifact",
    "ContributionPlan",
    "EntryPoint",
    "ErrorCode",
    "EvidenceKind",
    "EvidenceRecord",
    "GitHubIssue",
    "KeyPath",
    "LicenseInfo",
    "LicenseStatus",
    "PlannedChange",
    "ProposedEdit",
    "Orientation",
    "RelevantTest",
    "RepositoryInput",
    "RepositorySnapshot",
    "RunError",
    "RunEvent",
    "RunRecord",
    "RunStatus",
    "StageName",
    "TaskSource",
    "TaskType",
    "TestGuidance",
    "VerificationCheck",
    "VerificationReceipt",
    "VerificationStatus",
    "new_run_id",
    "utcnow",
]
