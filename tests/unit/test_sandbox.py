"""Phase 4 TDD: disposable verification sandbox.

These tests define the contract for running untrusted repository test
commands with hard bounds — wall-time kill, memory cap, env scrubbing,
output caps — and for honest NOT_RUN reasons when no supported toolchain
is detected.
"""

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from repomate_core.contracts import VerificationStatus
from repomate_core.verification.sandbox import (
    ProcessSandbox,
    SandboxLimits,
    detect_test_command,
    run_test_suite_check,
)


def _git(cwd: Path, *args: str) -> None:
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


def _mini_repo(tmp_path: Path, name: str, files: dict[str, str]) -> Path:
    repo = tmp_path / name
    repo.mkdir()
    for rel, content in files.items():
        target = repo / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8", newline="\n")
    _git(repo, "init", "-b", "main")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-m", "init")
    return repo


PYPROJECT = (
    "[project]\nname='t'\nversion='0.1.0'\n\n"
    "[tool.pytest.ini_options]\npythonpath=['src']\n"
)


def _repo_with_test(tmp_path: Path, name: str, test_body: str) -> Path:
    return _mini_repo(
        tmp_path,
        name,
        {
            "pyproject.toml": PYPROJECT,
            "src/t/__init__.py": "",
            "src/t/core.py": "def add(a, b):\n    return a + b\n",
            "tests/test_core.py": test_body,
        },
    )


class TestDetectTestCommand:
    def test_pytest_repo_detected(self, tmp_path):
        repo = _repo_with_test(tmp_path, "ok-repo", "def test_add():\n    assert add(1, 2) == 3\nfrom t.core import add\n")
        from repomate_core.repository.workspace import RepoWorkspace

        ws = RepoWorkspace.from_local(repo)
        cmd = detect_test_command(ws)
        assert cmd is not None
        assert cmd.name == "pytest"
        assert "pytest" in cmd.display

    def test_repo_without_toolchain_returns_none(self, tmp_path):
        repo = _mini_repo(tmp_path, "bare", {"README.md": "# bare\n"})
        from repomate_core.repository.workspace import RepoWorkspace

        assert detect_test_command(RepoWorkspace.from_local(repo)) is None


class TestProcessSandbox:
    def test_passing_suite(self, tmp_path):
        repo = _repo_with_test(
            tmp_path, "pass-repo", "from t.core import add\n\ndef test_add():\n    assert add(1, 2) == 3\n"
        )
        from repomate_core.repository.workspace import RepoWorkspace

        check = run_test_suite_check(
            RepoWorkspace.from_local(repo), limits=SandboxLimits(wall_time_seconds=60)
        )
        assert check.status is VerificationStatus.PASSED
        assert check.exit_code == 0
        assert check.command and "pytest" in check.command

    def test_failing_suite_reports_output(self, tmp_path):
        repo = _repo_with_test(
            tmp_path, "fail-repo", "from t.core import add\n\ndef test_add():\n    assert add(1, 2) == 4\n"
        )
        from repomate_core.repository.workspace import RepoWorkspace

        check = run_test_suite_check(
            RepoWorkspace.from_local(repo), limits=SandboxLimits(wall_time_seconds=60)
        )
        assert check.status is VerificationStatus.FAILED
        assert check.exit_code not in (0, None)
        assert "assert" in check.output_tail or "FAILED" in check.output_tail

    def test_wall_time_budget_kills_runaway_suite(self, tmp_path):
        repo = _repo_with_test(
            tmp_path, "slow-repo", "import time\n\ndef test_slow():\n    time.sleep(60)\n"
        )
        from repomate_core.repository.workspace import RepoWorkspace

        check = run_test_suite_check(
            RepoWorkspace.from_local(repo), limits=SandboxLimits(wall_time_seconds=5)
        )
        assert check.status is VerificationStatus.FAILED
        assert check.reason and "wall-time" in check.reason

    def test_environment_is_scrubbed(self, tmp_path, monkeypatch):
        monkeypatch.setenv("REPOMATE_SECRET_MARKER", "super-secret-value")
        repo = _repo_with_test(
            tmp_path,
            "env-repo",
            "import json, os\n\n"
            "def test_dump():\n"
            "    with open('envdump.json', 'w') as f:\n"
            "        json.dump(dict(os.environ), f)\n"
            "    assert True\n",
        )
        from repomate_core.repository.workspace import RepoWorkspace

        ws = RepoWorkspace.from_local(repo)
        run_test_suite_check(ws, limits=SandboxLimits(wall_time_seconds=60))
        dump = json.loads((repo / "envdump.json").read_text(encoding="utf-8"))
        assert "REPOMATE_SECRET_MARKER" not in dump
        assert "VYCE_API_KEY" not in dump
        assert "PATH" in dump  # minimal working environment kept

    def test_output_is_capped(self, tmp_path):
        repo = _repo_with_test(
            tmp_path,
            "noisy-repo",
            "def test_noisy():\n    print('x' * 1_000_000)\n    assert True\n",
        )
        from repomate_core.repository.workspace import RepoWorkspace

        check = run_test_suite_check(
            RepoWorkspace.from_local(repo), limits=SandboxLimits(wall_time_seconds=60)
        )
        assert len(check.output_tail) <= 2000

    def test_no_toolchain_is_honest_not_run(self, tmp_path):
        repo = _mini_repo(tmp_path, "no-tests", {"README.md": "# hi\n"})
        from repomate_core.repository.workspace import RepoWorkspace

        check = run_test_suite_check(
            RepoWorkspace.from_local(repo), limits=SandboxLimits()
        )
        assert check.status is VerificationStatus.NOT_RUN
        assert "no recognized test command" in check.reason

    @pytest.mark.skipif(
        os.name != "posix", reason="RLIMIT_AS is POSIX-only; Windows has no memory rlimit"
    )
    def test_memory_budget_caps_allocation(self, tmp_path):
        repo = _repo_with_test(
            tmp_path,
            "memory-repo",
            "def test_hungry():\n"
            "    blocks = []\n"
            "    try:\n"
            "        for _ in range(32):\n"
            "            blocks.append(bytearray(64 * 1024 * 1024))\n"
            "    except MemoryError:\n"
            "        raise AssertionError('memory capped')\n",
        )
        from repomate_core.repository.workspace import RepoWorkspace

        check = run_test_suite_check(
            RepoWorkspace.from_local(repo),
            limits=SandboxLimits(wall_time_seconds=90, memory_mb=256),
        )
        assert check.status is VerificationStatus.FAILED


class TestSandboxResultShape:
    def test_run_returns_typed_result(self, tmp_path):
        repo = _mini_repo(tmp_path, "echo-repo", {"noop.txt": "x\n"})
        sandbox = ProcessSandbox(SandboxLimits(wall_time_seconds=10))
        result = sandbox.run([sys.executable, "-c", "pass"], cwd=repo)
        assert result.exit_code == 0
        assert result.timed_out is False
