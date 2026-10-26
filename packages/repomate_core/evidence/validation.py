"""Structural validation for evidence retrieved by a model tool call.

The model chooses *where* to look; this module decides whether what came
back is a real, current citation. Every item is re-read from the pinned
workspace and the snippet is rebuilt from the actual lines, so a model can
never inject a fabricated path, line range or snippet into the evidence set.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import PurePosixPath
from typing import Optional

from repomate_core.contracts import (
    EvidenceKind,
    EvidenceRecord,
    RepositorySnapshot,
)
from repomate_core.repository.workspace import RepoWorkspace

MAX_EVIDENCE_CHARS = 4000
MAX_VALIDATION_BYTES = 300_000


@dataclass(frozen=True)
class EvidenceValidation:
    """Outcome of validating one retrieved item."""

    record: Optional[EvidenceRecord] = None
    reason: str = ""

    @property
    def ok(self) -> bool:
        return self.record is not None


def normalize_evidence_path(raw: str) -> Optional[str]:
    """Return a safe repository-relative POSIX path, or ``None``."""
    candidate = (raw or "").strip().replace("\\", "/")
    if not candidate or "\x00" in candidate:
        return None
    while candidate.startswith("./"):
        candidate = candidate[2:]
    if candidate.startswith("/"):
        return None
    path = PurePosixPath(candidate)
    if path.is_absolute() or ".." in path.parts or ".git" in path.parts:
        return None
    return path.as_posix()


def validate_retrieved_evidence(
    ws: RepoWorkspace,
    snapshot: RepositorySnapshot,
    *,
    path: str,
    start_line: int,
    end_line: int,
    kind: EvidenceKind,
    rationale: str,
    tracked: Optional[set[str]] = None,
) -> EvidenceValidation:
    """Build a citation only when it resolves against the pinned workspace.

    The returned record's snippet comes from the file, never from the model.
    A missing/untracked path, a stale commit, an out-of-range line span or an
    oversized citation is rejected with a human-readable reason.
    """
    normalized = normalize_evidence_path(path)
    if normalized is None:
        return EvidenceValidation(reason=f"unsafe or empty path: {path!r}")

    try:
        tracked_paths = tracked if tracked is not None else set(ws.ls_files())
    except Exception as exc:  # noqa: BLE001 - report a validation failure
        return EvidenceValidation(reason=f"could not list tracked files: {exc}")
    if normalized not in tracked_paths:
        return EvidenceValidation(
            reason=f"{normalized!r} is not a tracked file in the pinned snapshot"
        )

    try:
        actual_commit = ws.commit_sha
    except Exception as exc:  # noqa: BLE001
        return EvidenceValidation(reason=f"could not read workspace commit: {exc}")
    if actual_commit != snapshot.commit_sha:
        return EvidenceValidation(
            reason=(
                "workspace is no longer at the pinned commit "
                f"{snapshot.commit_sha[:10]}"
            )
        )

    if start_line < 1 or end_line < start_line:
        return EvidenceValidation(
            reason=f"invalid line range {start_line}-{end_line}"
        )

    try:
        text, _size, _truncated = ws.read_text_bounded(
            normalized, max_bytes=MAX_VALIDATION_BYTES
        )
    except Exception as exc:  # noqa: BLE001
        return EvidenceValidation(reason=f"could not read {normalized!r}: {exc}")

    lines = text.splitlines()
    if end_line > len(lines):
        return EvidenceValidation(
            reason=(
                f"line range {start_line}-{end_line} is outside {normalized!r} "
                f"({len(lines)} line(s) available)"
            )
        )
    snippet = "\n".join(lines[start_line - 1 : end_line])
    if not snippet.strip():
        return EvidenceValidation(
            reason=f"lines {start_line}-{end_line} of {normalized!r} are empty"
        )
    if len(snippet) > MAX_EVIDENCE_CHARS:
        return EvidenceValidation(
            reason=(
                f"line range {start_line}-{end_line} of {normalized!r} is "
                f"{len(snippet)} characters, above the {MAX_EVIDENCE_CHARS}-"
                "character evidence cap"
            )
        )

    return EvidenceValidation(
        record=EvidenceRecord(
            id="",
            kind=kind,
            path=normalized,
            start_line=start_line,
            end_line=end_line,
            snippet=snippet,
            rationale=rationale,
        )
    )
