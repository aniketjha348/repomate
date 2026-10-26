"""The reviewable artifacts a run produces."""

from __future__ import annotations

from pydantic import BaseModel, Field

from repomate_core.contracts.enums import ArtifactKind


class ContributionArtifact(BaseModel):
    """The primary reviewable diff (docs fix, test diff or code patch)."""

    kind: ArtifactKind
    patch: str
    affected_paths: list[str]
    based_on_commit: str
    generated_by: str


class ArtifactDocument(BaseModel):
    """A downloadable document published alongside the primary diff.

    ``CONTRIBUTION_PLAN.md`` and ``REPRO_CHECKLIST.md`` are not diffs, so they
    are kept out of ``ContributionArtifact.patch``. They still cross the same
    process boundaries (run record, HTTP download) and carry the same
    provenance fields as a reviewable artifact.
    """

    name: str = Field(
        min_length=1,
        max_length=120,
        pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]*$",
    )
    kind: ArtifactKind
    media_type: str = "text/markdown; charset=utf-8"
    content: str
    generated_by: str = ""
