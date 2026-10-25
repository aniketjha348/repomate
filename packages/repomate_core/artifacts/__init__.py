"""Artifact generation and patch policy."""

from repomate_core.artifacts.generator import generate_docs_artifact
from repomate_core.artifacts.patch import (
    DOCS_PATCH_POLICY,
    PatchPolicy,
    extract_affected_paths,
    validate_patch,
)

__all__ = [
    "DOCS_PATCH_POLICY",
    "PatchPolicy",
    "extract_affected_paths",
    "generate_docs_artifact",
    "validate_patch",
]
