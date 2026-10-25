"""Unified-diff parsing and path policy enforcement.

Patch integrity rules (docs/security.md):

- paths are taken from ``+++ b/`` headers; traversal (``..``) and absolute
  paths are rejected outright
- every touched path must match the policy's allow patterns and none of
  its deny patterns
- total patch size is capped so a runaway model cannot emit a rewrite
"""

from __future__ import annotations

import fnmatch
from typing import Iterable

from pydantic import BaseModel, Field

from repomate_core.contracts import ArtifactKind

MAX_PATCH_LINES = 2000


class PatchPolicyError(ValueError):
    """Raised for structurally unsafe patches (traversal/absolute paths)."""


class PatchPolicy(BaseModel):
    artifact_kind: ArtifactKind
    allow: list[str] = Field(default_factory=list)
    deny: list[str] = Field(default_factory=list)

    def violations_for(self, paths: Iterable[str]) -> list[str]:
        violations: list[str] = []
        for path in paths:
            posix = path.replace("\\", "/")
            if any(_matches(posix, pattern) for pattern in self.deny):
                violations.append(f"path {path!r} matches a forbidden pattern")
            elif not any(_matches(posix, pattern) for pattern in self.allow):
                violations.append(f"path {path!r} is outside the allowed paths for {self.artifact_kind.value}")
        return violations


DOCS_PATCH_POLICY = PatchPolicy(
    artifact_kind=ArtifactKind.DOCS_DIFF,
    allow=["README*", "README*/*", "*.md", "*.rst", "docs/**", "doc/**", "*.txt"],
    deny=[
        ".github/**", ".git*", "**/.git*", "**/*.lock", "**/package-lock.json",
        "**/.env*", "**/secrets/**", "**/id_rsa*", "**/*.pem", "**/*.key",
    ],
)


def _matches(posix_path: str, pattern: str) -> bool:
    if pattern.endswith("/**"):
        return posix_path.startswith(pattern[:-2])
    if fnmatch.fnmatch(posix_path, pattern):
        return True
    return fnmatch.fnmatch(posix_path.rsplit("/", 1)[-1], pattern)


def extract_affected_paths(patch: str) -> list[str]:
    """Return the unique touched paths from a unified diff, enforcing
    structural safety while parsing."""
    paths: list[str] = []
    seen: set[str] = set()
    for line in patch.splitlines():
        if not line.startswith("+++ b/"):
            continue
        path = line[len("+++ b/") :].strip()
        if not path or path == "/dev/null":
            continue
        posix = path.replace("\\", "/")
        if posix.startswith("/") or posix.startswith("~"):
            raise PatchPolicyError(f"absolute path in diff: {path!r}")
        parts = [p for p in posix.split("/") if p not in ("", ".")]
        if ".." in parts:
            raise PatchPolicyError(f"path traversal in diff: {path!r}")
        clean = "/".join(parts)
        if clean not in seen:
            seen.add(clean)
            paths.append(clean)
    return paths


def validate_patch(patch: str, policy: PatchPolicy) -> list[str]:
    """Return a list of policy violations (empty means compliant)."""
    violations: list[str] = []
    lines = patch.splitlines()
    if len(lines) > MAX_PATCH_LINES:
        violations.append(f"patch exceeds {MAX_PATCH_LINES} lines")
    try:
        paths = extract_affected_paths(patch)
    except PatchPolicyError as exc:
        return [str(exc)]
    if not paths:
        violations.append("patch touches no files")
    violations.extend(policy.violations_for(paths))
    return violations
