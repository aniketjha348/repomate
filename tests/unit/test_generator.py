"""Unit tests for the documentation artifact generator."""

import pytest

from repomate_core.artifacts.generator import generate_docs_artifact
from repomate_core.contracts import (
    ContributionPlan,
    EvidenceRecord,
    PlannedChange,
    TaskType,
)


def _plan(target: str) -> ContributionPlan:
    return ContributionPlan(
        task_type=TaskType.DOCUMENTATION,
        summary=f"Documentation change in {target}",
        planned_changes=[PlannedChange(path=target, change_type="MODIFY", rationale="")],
        evidence_ids=["ev1"],
        planned_by="heuristic-v1",
    )


def _evidence() -> list[EvidenceRecord]:
    return [
        EvidenceRecord(
            id="ev1",
            kind="DOC",
            path="docs/usage.md",
            start_line=3,
            end_line=9,
            snippet="...",
            rationale="",
        )
    ]


def test_generates_patch_and_resets_workspace(local_workspace):
    sha_before = local_workspace.commit_sha
    clean_before = local_workspace.git("status", "--porcelain").stdout

    artifact = generate_docs_artifact(
        local_workspace,
        _plan("README.md"),
        "Add documentation for the timeout option to the README",
        _evidence(),
    )

    assert artifact.kind.value == "DOCS_DIFF"
    assert artifact.affected_paths == ["README.md"]
    assert artifact.based_on_commit == sha_before
    assert "## " in artifact.patch and "diff --git" in artifact.patch
    assert "docs/usage.md, lines 3-9" in artifact.patch  # evidence citation
    assert local_workspace.git("status", "--porcelain").stdout == clean_before


def test_duplicate_section_is_refused(local_repo, local_workspace):
    # Commit a section whose normalized title matches what the task would
    # generate; the generator must refuse to duplicate it.
    readme = local_repo / "README.md"
    readme.write_text(
        readme.read_text(encoding="utf-8").rstrip()
        + "\n\n## Documentation for the timeout option to the README\n\nExists.\n",
        encoding="utf-8", newline="\n",
    )
    local_workspace.git("add", "-A")
    local_workspace.git("-c", "user.name=Fixture Bot", "-c", "user.email=bot@example.invalid",
                        "commit", "-m", "document timeout already")

    with pytest.raises(ValueError, match="already exists"):
        generate_docs_artifact(
            local_workspace,
            _plan("README.md"),
            "Add documentation for the timeout option to the README",
            _evidence(),
        )
    local_workspace.reset_hard()
