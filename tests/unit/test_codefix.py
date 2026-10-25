"""Code-fix artifact generation: exact-anchor search/replace edits."""

import pytest

from repomate_core.artifacts.codefix import (
    EditAnchorError,
    apply_proposed_edits,
)
from repomate_core.contracts import (
    ContributionPlan,
    PlannedChange,
    ProposedEdit,
    TaskType,
)


def _plan(edits: list[ProposedEdit]) -> ContributionPlan:
    return ContributionPlan(
        task_type=TaskType.BUG_FIX,
        summary="fix the off-by-one",
        planned_changes=[PlannedChange(path=edits[0].path if edits else "x",
                                       change_type="MODIFY", rationale="")],
        proposed_edits=edits,
        planned_by="model:openai/deepseek-v4.1",
    )


def test_exact_anchor_replace_produces_patch(local_workspace):
    artifact = apply_proposed_edits(
        local_workspace,
        _plan([
            ProposedEdit(
                path="src/fixture/core.py",
                old_text="return [transform(item) for item in items]",
                new_text="return [transform(item) for item in items or []]",
                rationale="guard against None",
            )
        ]),
    )
    assert artifact.kind.value == "PATCH_DIFF"
    assert artifact.affected_paths == ["src/fixture/core.py"]
    assert "or []" in artifact.patch
    assert "diff --git" in artifact.patch
    # Workspace left clean.
    assert local_workspace.git("status", "--porcelain").stdout.strip() == ""


def test_missing_anchor_is_typed_error(local_workspace):
    with pytest.raises(EditAnchorError, match="anchor not found"):
        apply_proposed_edits(
            local_workspace,
            _plan([
                ProposedEdit(
                    path="src/fixture/core.py",
                    old_text="this line does not exist in the file",
                    new_text="replacement",
                )
            ]),
        )
    assert local_workspace.git("status", "--porcelain").stdout.strip() == ""


def test_ambiguous_anchor_is_rejected(local_workspace):
    with pytest.raises(EditAnchorError, match="ambiguous"):
        apply_proposed_edits(
            local_workspace,
            _plan([
                ProposedEdit(
                    path="src/fixture/core.py",
                    old_text="item",  # occurs in several lines
                    new_text="entry",
                )
            ]),
        )


def test_empty_old_text_creates_file(local_workspace):
    artifact = apply_proposed_edits(
        local_workspace,
        _plan([
            ProposedEdit(
                path="docs/notes.md",
                old_text="",
                new_text="# Notes\n\nAdded by RepoMate.\n",
                rationale="document the fix",
            )
        ]),
    )
    assert "docs/notes.md" in artifact.affected_paths
    assert local_workspace.git("status", "--porcelain").stdout.strip() == ""


def test_multi_file_edits_single_patch(local_workspace):
    artifact = apply_proposed_edits(
        local_workspace,
        _plan([
            ProposedEdit(
                path="src/fixture/core.py",
                old_text="timeout=30",
                new_text="timeout=60",
                rationale="raise default",
            ),
            ProposedEdit(
                path="docs/usage.md",
                old_text="documented in the README quickstart",
                new_text="documented in the README quickstart (timeout default: 30s)",
                rationale="keep docs in sync",
            ),
        ]),
    )
    assert set(artifact.affected_paths) == {"src/fixture/core.py", "docs/usage.md"}
    assert artifact.patch.count("diff --git") == 2
