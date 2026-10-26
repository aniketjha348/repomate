"""Unit tests for repository inspection edge cases (bug-fix regressions)."""

import json
import subprocess
from pathlib import Path

import pytest

from repomate_core.repository.inspect import inspect_repository
from repomate_core.repository.workspace import RepoWorkspace


def _git(cwd: Path, *args: str) -> None:
    import os

    env = dict(
        os.environ,
        GIT_AUTHOR_NAME="T",
        GIT_AUTHOR_EMAIL="t@t.invalid",
        GIT_COMMITTER_NAME="T",
        GIT_COMMITTER_EMAIL="t@t.invalid",
    )
    result = subprocess.run(
        ["git", *args], cwd=str(cwd), capture_output=True, text=True, env=env
    )
    assert result.returncode == 0, result.stderr


@pytest.fixture
def manifest_only_repo(tmp_path: Path) -> RepoWorkspace:
    """A repo with lowercase readme.md and license only in package.json —
    the exact shape that used to break detection (slugify-style)."""
    repo = tmp_path / "manifest-only"
    repo.mkdir()
    (repo / "readme.md").write_text("# lower\n\nUsage docs here.\n", encoding="utf-8")
    (repo / "index.js").write_text("module.exports = {};\n", encoding="utf-8")
    (repo / "package.json").write_text(
        json.dumps({"name": "manifest-only", "license": "MIT"}), encoding="utf-8"
    )
    _git(repo, "init", "-b", "main")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-m", "init")
    return RepoWorkspace.from_local(repo)


def test_readme_detected_case_insensitive(manifest_only_repo):
    snapshot = inspect_repository(
        manifest_only_repo, owner="a", name="b", url="https://github.com/a/b"
    )
    assert snapshot.readme_path == "readme.md"


def test_manifest_declared_license_recognized_with_note(manifest_only_repo):
    snapshot = inspect_repository(
        manifest_only_repo, owner="a", name="b", url="https://github.com/a/b"
    )
    license_info = snapshot.license
    assert license_info.status.value == "RECOGNIZED"
    assert license_info.spdx_id == "MIT"
    assert "package manifest" in license_info.note
    assert license_info.file_path is None


def test_license_file_beats_manifest(local_workspace):
    snapshot = inspect_repository(
        local_workspace, owner="a", name="b", url="https://github.com/a/b"
    )
    assert snapshot.license.file_path == "LICENSE"
    assert snapshot.license.spdx_id == "MIT"
    assert "content" in snapshot.license.note


def _committed_repo(path: Path) -> RepoWorkspace:
    _git(path, "init", "-b", "main")
    _git(path, "add", "-A")
    _git(path, "commit", "-m", "init")
    return RepoWorkspace.from_local(path)


def test_pyproject_table_form_license_recognized(tmp_path: Path):
    repo = tmp_path / "table-license"
    repo.mkdir()
    (repo / "pyproject.toml").write_text(
        '[project]\nname = "table-license"\nlicense = { text = "Apache-2.0" }\n',
        encoding="utf-8",
    )
    snapshot = inspect_repository(
        _committed_repo(repo), owner="a", name="b", url="https://github.com/a/b"
    )
    assert snapshot.license.status.value == "RECOGNIZED"
    assert snapshot.license.spdx_id == "Apache-2.0"


def test_package_json_bin_string_is_a_path(tmp_path: Path):
    repo = tmp_path / "bin-string"
    repo.mkdir()
    (repo / "cli.js").write_text("#!/usr/bin/env node\n", encoding="utf-8")
    (repo / "package.json").write_text(
        json.dumps({"name": "bin-string", "bin": "./cli.js"}), encoding="utf-8"
    )
    snapshot = inspect_repository(
        _committed_repo(repo), owner="a", name="b", url="https://github.com/a/b"
    )
    assert "./cli.js" in [entry.path for entry in snapshot.entry_points]


def test_package_json_bin_mapping_uses_paths_not_command_names(tmp_path: Path):
    repo = tmp_path / "bin-map"
    repo.mkdir()
    (repo / "bin").mkdir()
    (repo / "bin" / "tool.js").write_text("#!/usr/bin/env node\n", encoding="utf-8")
    (repo / "package.json").write_text(
        json.dumps({"name": "bin-map", "bin": {"tool": "bin/tool.js"}}),
        encoding="utf-8",
    )
    snapshot = inspect_repository(
        _committed_repo(repo), owner="a", name="b", url="https://github.com/a/b"
    )
    paths = [entry.path for entry in snapshot.entry_points]
    assert "bin/tool.js" in paths
    assert "tool" not in paths
