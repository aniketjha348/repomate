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
        planned_by="model:openai/gemma4:31b",
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


def test_empty_old_text_refuses_to_overwrite_existing_file(local_workspace):
    with pytest.raises(EditAnchorError, match="already exists"):
        apply_proposed_edits(
            local_workspace,
            _plan([
                ProposedEdit(
                    path="README.md",
                    old_text="",
                    new_text="replacement that would delete the README\n",
                    rationale="not actually a create",
                )
            ]),
        )
    # The original README is still intact.
    assert "fixture-project" in local_workspace.read_text("README.md")


def test_edit_does_not_truncate_large_file(local_workspace, local_repo):
    large = local_repo / "src" / "fixture" / "large.py"
    large.write_text(
        "HEAD\n" + ("x" * 350_000) + "\nTAIL_MARKER\n",
        encoding="utf-8",
        newline="\n",
    )
    local_workspace.git("add", "-A")
    local_workspace.git(
        "-c", "user.name=T", "-c", "user.email=t@t.invalid",
        "commit", "-m", "add large fixture file",
    )

    artifact = apply_proposed_edits(
        local_workspace,
        _plan([
            ProposedEdit(
                path="src/fixture/large.py",
                old_text="HEAD",
                new_text="HEAD2",
                rationale="rename the marker",
            )
        ]),
    )
    assert "HEAD2" in artifact.patch
    # Apply the patch and prove the 350k tail survived; a truncated read
    # would have produced a diff that deletes it.
    local_workspace.apply(artifact.patch)
    patched = local_workspace.read_text("src/fixture/large.py", max_chars=None)
    assert "TAIL_MARKER" in patched
    local_workspace.reset_hard()


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
