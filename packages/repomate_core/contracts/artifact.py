"""The reviewable artifact a run produces."""

from __future__ import annotations

from pydantic import BaseModel

from repomate_core.contracts.enums import ArtifactKind


class ContributionArtifact(BaseModel):
    kind: ArtifactKind
    patch: str
    affected_paths: list[str]
    based_on_commit: str
    generated_by: str
