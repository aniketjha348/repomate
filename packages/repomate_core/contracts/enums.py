"""Enumerations crossing process boundaries (HTTP, disk, SSE)."""

from __future__ import annotations

import enum


class RunStatus(str, enum.Enum):
    PENDING = "PENDING"
    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"
    NEED_MORE_INFO = "NEED_MORE_INFO"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


class ErrorCode(str, enum.Enum):
    """Machine-readable failure causes surfaced to clients."""

    INVALID_INPUT = "INVALID_INPUT"
    UNSUPPORTED_INPUT = "UNSUPPORTED_INPUT"
    RATE_LIMITED = "RATE_LIMITED"
    NETWORK = "NETWORK_ERROR"
    MODEL = "MODEL_ERROR"
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


class VerificationStatus(str, enum.Enum):
    PASSED = "PASSED"
    FAILED = "FAILED"
    NOT_RUN = "NOT_RUN"
