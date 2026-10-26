"""Shared fixtures.

The local repository fixture keeps the suite hermetic: the full pipeline
is exercised against a real git checkout without touching the network.
Network-dependent tests live in ``tests/e2e`` and are opt-in (``-m network``).
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

# Set before any test imports an entry point: a developer's local ``.env``
# must never change a test outcome. Tests that exercise the loader itself
# re-enable it explicitly.
os.environ["REPOMATE_SKIP_DOTENV"] = "1"

from repomate_core.contracts import RepositoryInput, TaskSource
from repomate_core.repository.workspace import RepoWorkspace

MIT_LICENSE = (
    "MIT License\n\n"
    "Copyright (c) 2026 Fixture Author\n\n"
    "Permission is hereby granted, free of charge, to any person obtaining a copy "
    "of this software and associated documentation files (the \"Software\"), to deal "
    "in the Software without restriction.\n"
)

README = """# fixture-project

A tiny Python project used as a RepoMate test fixture.

## Quickstart

    pip install fixture-project
    export FIXTURE_API_KEY=secret

## Configuration

The client reads `FIXTURE_TIMEOUT` to control the request timeout in
seconds. Retries honour `FIXTURE_RETRIES`.
"""

USAGE = """# Usage guide

Run the processor:

    fixture process --input data.csv

Timeouts and retries are configured through the environment variables
documented in the README quickstart.
"""

CORE_PY = '''"""Core processing helpers."""


def process(items, timeout=30):
    """Process items with a request timeout (seconds)."""
    return [transform(item) for item in items]


def transform(item):
    return str(item).strip().lower()
'''

TEST_PY = '''from fixture.core import process


def test_process_applies_timeout_default():
    assert process(["A "])[0] == "a"
'''


def _git(cwd: Path, *args: str) -> None:
    env = {
        "GIT_AUTHOR_NAME": "Fixture Bot",
        "GIT_AUTHOR_EMAIL": "bot@example.invalid",
        "GIT_COMMITTER_NAME": "Fixture Bot",
        "GIT_COMMITTER_EMAIL": "bot@example.invalid",
        "GIT_TERMINAL_PROMPT": "0",
    }
    import os

    env_full = dict(os.environ, **env)
    result = subprocess.run(
        ["git", *args], cwd=str(cwd), capture_output=True, text=True,
        encoding="utf-8", env=env_full,
    )
    assert result.returncode == 0, f"git {args} failed: {result.stderr}"


@pytest.fixture(autouse=True)
def _isolate_model_environment(monkeypatch):
    """Prevent an operator's exported Ollama credentials from changing a run."""
    for key in (
        "OLLAMA_API_KEY",
        "OLLAMA_BASE_URL",
        "OLLAMA_MODEL",
        "OLLAMA_MODELS",
    ):
        monkeypatch.delenv(key, raising=False)


@pytest.fixture(autouse=True)
def _reset_fair_use_state():
    """Keep per-IP windows and counters independent between tests."""
    from services.api import fair_use

    fair_use.reset_state()
    yield
    fair_use.reset_state()


@pytest.fixture
def local_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "fixture-project"
    (repo / "docs").mkdir(parents=True)
    (repo / "src" / "fixture").mkdir(parents=True)
    (repo / "tests").mkdir()

    (repo / "README.md").write_text(README, encoding="utf-8", newline="\n")
    (repo / "docs" / "usage.md").write_text(USAGE, encoding="utf-8", newline="\n")
    (repo / "LICENSE").write_text(MIT_LICENSE, encoding="utf-8", newline="\n")
    (repo / "pyproject.toml").write_text(
        "[project]\nname = 'fixture-project'\nversion = '0.1.0'\n\n"
        "[project.scripts]\nfixture = 'fixture.cli:main'\n\n"
        "[tool.pytest.ini_options]\npythonpath = ['src']\n",
        encoding="utf-8", newline="\n",
    )
    (repo / "src" / "fixture" / "__init__.py").write_text("", encoding="utf-8")
    (repo / "src" / "fixture" / "core.py").write_text(CORE_PY, encoding="utf-8", newline="\n")
    (repo / "tests" / "test_core.py").write_text(TEST_PY, encoding="utf-8", newline="\n")

    _git(repo, "init", "-b", "main")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-m", "fixture initial commit")
    return repo


@pytest.fixture
def local_workspace(local_repo: Path) -> RepoWorkspace:
    return RepoWorkspace.from_local(local_repo)


@pytest.fixture
def docs_task_input() -> RepositoryInput:
    return RepositoryInput(
        source=TaskSource.REPO_TASK,
        repo_url="https://github.com/acme/fixture-project",
        task="Add documentation for the timeout option to the README quickstart",
    )
