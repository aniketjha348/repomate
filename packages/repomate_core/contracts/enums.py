"""Enumerations crossing process boundaries (HTTP, disk, SSE)."""

from __future__ import annotations

import enum


class RunStatus(str, enum.Enum):
    PENDING = "PENDING"
    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"
    NEED_MORE_INFO = "NEED_MORE_INFO"
    # The run stopped at an explicit retrieval/resource limit. Evidence and
    # orientation may be published, but the analysis does not cover the whole
    # repository and must not be presented as complete.
    PARTIAL = "PARTIAL"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


class ErrorCode(str, enum.Enum):
    """Machine-readable failure causes surfaced to clients."""

    INVALID_INPUT = "INVALID_INPUT"
    UNSUPPORTED_INPUT = "UNSUPPORTED_INPUT"
    RATE_LIMITED = "RATE_LIMITED"
    NETWORK = "NETWORK_ERROR"
    MODEL = "MODEL_ERROR"
    # A fair-use budget (model calls/tokens, runtime, tool retrieval) was
    # exhausted before the requested work could finish. Distinct from a
    # gateway failure so reports can name the actual cause.
    BUDGET_EXCEEDED = "BUDGET_EXCEEDED"
    TIMEOUT = "TIMEOUT"
    INTERNAL = "INTERNAL_ERROR"


class StageName(str, enum.Enum):
    VALIDATE_INPUT = "VALIDATE_INPUT"
    PIN_SNAPSHOT = "PIN_SNAPSHOT"
    RETRIEVE_EVIDENCE = "RETRIEVE_EVIDENCE"
    PLAN = "PLAN"
    GENERATE_ARTIFACT = "GENERATE_ARTIFACT"
    VERIFY = "VERIFY"
    PUBLISH = "PUBLISH"


class TaskSource(str, enum.Enum):
    GITHUB_ISSUE = "GITHUB_ISSUE"
    REPO_TASK = "REPO_TASK"


class LicenseStatus(str, enum.Enum):
    RECOGNIZED = "RECOGNIZED"
    UNKNOWN = "UNKNOWN"
    ABSENT = "ABSENT"


class EvidenceKind(str, enum.Enum):
    ISSUE = "ISSUE"
    DOC = "DOC"
    SOURCE = "SOURCE"
    TEST = "TEST"
    METADATA = "METADATA"


class TaskType(str, enum.Enum):
    DOCUMENTATION = "DOCUMENTATION"
    BUG_FIX = "BUG_FIX"
    TEST = "TEST"
    FEATURE = "FEATURE"
    REFACTOR = "REFACTOR"
    UNKNOWN = "UNKNOWN"


class ArtifactKind(str, enum.Enum):
    DOCS_DIFF = "DOCS_DIFF"
    PATCH_DIFF = "PATCH_DIFF"
    TEST_DIFF = "TEST_DIFF"
    REPRO_CHECKLIST = "REPRO_CHECKLIST"
    # Markdown contribution plan, downloadable as CONTRIBUTION_PLAN.md. It is
    # a document rather than a diff, so it is carried in ``RunRecord.documents``
    # instead of ``RunRecord.artifact``.
    CONTRIBUTION_PLAN = "CONTRIBUTION_PLAN"


class VerificationStatus(str, enum.Enum):
    PASSED = "PASSED"
    FAILED = "FAILED"
    NOT_RUN = "NOT_RUN"


class RetrievalStatus(str, enum.Enum):
    """Whether repository retrieval covered its complete permitted scope."""

    COMPLETE = "COMPLETE"
    PARTIAL = "PARTIAL"


class RetrievalLimit(str, enum.Enum):
    """The explicit retrieval budget that was reached."""

    MAX_FILES = "MAX_FILES"
    MAX_BYTES_PER_FILE = "MAX_BYTES_PER_FILE"
    MAX_TOTAL_BYTES = "MAX_TOTAL_BYTES"
    MAX_SEARCH_RESULTS = "MAX_SEARCH_RESULTS"
    MAX_SECONDS = "MAX_SECONDS"


class ComparisonOutcome(str, enum.Enum):
    """Deterministic baseline-vs-patched classification.

    The comparison is derived only from the two runs' statuses and the
    command they executed; no model judgment participates.
    """

    CONSISTENT_IMPROVEMENT = "CONSISTENT_IMPROVEMENT"
    NO_REGRESSION_DETECTED = "NO_REGRESSION_DETECTED"
    UNRESOLVED = "UNRESOLVED"
    POTENTIAL_REGRESSION = "POTENTIAL_REGRESSION"
    BASELINE_INCOMPLETE = "BASELINE_INCOMPLETE"
    POST_PATCH_INCOMPLETE = "POST_PATCH_INCOMPLETE"
