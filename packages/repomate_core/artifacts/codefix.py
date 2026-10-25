"""Code-fix artifact generation from model-proposed edits.

Each edit is an exact-anchor search/replace: ``old_text`` must appear
verbatim and uniquely in the pinned file (empty ``old_text`` creates a
new file). All edits apply all-or-nothing — an anchor that does not
match the snapshot is a typed failure, never a silent partial patch.
The workspace is reset afterwards; the patch text is the only lasting
output, exactly like the docs generator.
"""

from __future__ import annotations

from repomate_core.artifacts.patch import extract_affected_paths
from repomate_core.contracts import (
    ArtifactKind,
    ContributionArtifact,
    ContributionPlan,
)
from repomate_core.repository.workspace import RepoWorkspace


class EditAnchorError(ValueError):
    """A proposed edit did not anchor to the pinned snapshot."""


def apply_proposed_edits(
    ws: RepoWorkspace, plan: ContributionPlan
) -> ContributionArtifact:
    edits = plan.proposed_edits
    if not edits:
        raise ValueError("plan carries no proposed edits to apply")

    base_sha = ws.commit_sha
    touched: list[str] = []

    for edit in edits:
        if edit.old_text == "":
            existing = ""
        else:
            existing = _read_existing(ws, edit.path)
            occurrences = existing.count(edit.old_text)
            if occurrences == 0:
                raise EditAnchorError(
                    f"edit anchor not found in {edit.path}: {edit.old_text[:80]!r}"
                )
            if occurrences > 1:
                raise EditAnchorError(
                    f"edit anchor ambiguous in {edit.path} "
                    f"({occurrences} occurrences): {edit.old_text[:80]!r}"
                )
        ws.write_text(edit.path, existing.replace(edit.old_text, edit.new_text, 1))
        if edit.path not in touched:
            touched.append(edit.path)
        if edit.old_text == "":
            ws.stage_intent_to_add(edit.path)

    patch = ws.diff()
    ws.reset_hard()

    affected = extract_affected_paths(patch)
    return ContributionArtifact(
        kind=ArtifactKind.PATCH_DIFF,
        patch=patch,
        affected_paths=affected,
        based_on_commit=base_sha,
        generated_by=plan.planned_by,
    )


def _read_existing(ws: RepoWorkspace, path: str) -> str:
    try:
        return ws.read_text(path)
    except Exception as exc:
        raise EditAnchorError(f"cannot read target file {path!r}: {exc}") from exc
