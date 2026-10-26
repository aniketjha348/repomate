"""Independent equivalent checkouts for baseline/post-patch verification."""

from pathlib import Path

import pytest

from repomate_core.repository.errors import WorkspaceError
from repomate_core.repository.workspace import RepoWorkspace


def test_clone_is_pinned_and_independent(local_repo: Path, tmp_path: Path):
    source = RepoWorkspace.from_local(local_repo)
    # Uncommitted source content must not leak into an equivalent checkout.
    (local_repo / "scratch.txt").write_text("not committed\n", encoding="utf-8")

    clone = source.clone_to(tmp_path / "baseline")

    assert clone.commit_sha == source.commit_sha
    assert clone.ls_files() == source.ls_files()
    assert not (clone.root / "scratch.txt").exists()

    (clone.root / "clone-only.txt").write_text("clone\n", encoding="utf-8")
    assert not (local_repo / "clone-only.txt").exists()

    (local_repo / "src" / "fixture" / "core.py").write_text(
        "# source-only change\n", encoding="utf-8", newline="\n"
    )
    clone.git("reset", "--hard", "HEAD")
    assert "source-only change" not in (clone.root / "src" / "fixture" / "core.py").read_text(
        encoding="utf-8"
    )


def test_two_clones_are_separate_workspaces(local_repo: Path, tmp_path: Path):
    source = RepoWorkspace.from_local(local_repo)

    baseline = source.clone_to(tmp_path / "baseline")
    patched = source.clone_to(tmp_path / "patched")

    assert baseline.root != patched.root
    assert baseline.root != source.root
    (patched.root / "patched-only.txt").write_text("patched\n", encoding="utf-8")
    assert not (baseline.root / "patched-only.txt").exists()
    assert not (source.root / "patched-only.txt").exists()


def test_clone_refuses_existing_destination(local_repo: Path, tmp_path: Path):
    source = RepoWorkspace.from_local(local_repo)
    existing = tmp_path / "already-there"
    existing.mkdir()

    with pytest.raises(WorkspaceError, match="already exists"):
        source.clone_to(existing)
