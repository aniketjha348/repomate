"""End-to-end: a malicious repository's test suite cannot exfiltrate.

These run a real repository test suite through the real sandbox path
(``run_test_suite_check``) and through the full verification runner, so the
boundary is exercised exactly where untrusted code actually executes — not
through a mocked policy object.

The repository under test is a genuine git checkout whose tests try to reach
the network, read application secrets, and touch internal services.
"""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

import pytest

from repomate_core.contracts import VerificationStatus
from repomate_core.verification.network_policy import EgressBackend, detect_egress_backend
from repomate_core.verification.sandbox import (
    SandboxLimits,
    run_egress_probe_check,
    run_test_suite_check,
)
from repomate_core.repository.workspace import RepoWorkspace

pytestmark = pytest.mark.skipif(
    os.name != "posix", reason="network namespaces are a POSIX/Linux mechanism"
)

BACKEND = detect_egress_backend()
requires_backend = pytest.mark.skipif(
    BACKEND is EgressBackend.NONE, reason="no egress-enforcement backend on this host"
)

PYPROJECT = "[project]\nname='exfil'\nversion='0.1.0'\n\n[tool.pytest.ini_options]\n"

# A test suite that does exactly what a hostile repository would do.
EXFIL_TEST = '''"""A hostile test suite: try to phone home and steal credentials."""
import json
import os
import socket

FINDINGS = {}


def _try(name, host, port):
    try:
        sock = socket.create_connection((host, port), timeout=3)
        sock.close()
        FINDINGS[name] = "reachable"
    except Exception as exc:
        FINDINGS[name] = "blocked:" + type(exc).__name__


def test_attempt_exfiltration():
    _try("public", "1.1.1.1", 80)
    _try("metadata", "169.254.169.254", 80)
    _try("private", "10.0.0.1", 80)
    _try("postgres", "127.0.0.1", 5432)
    _try("redis", "127.0.0.1", 6379)
    _try("api", "127.0.0.1", 8000)
    try:
        socket.gethostbyname("example.com")
        FINDINGS["dns"] = "reachable"
    except Exception as exc:
        FINDINGS["dns"] = "blocked:" + type(exc).__name__

    secrets = {
        key: value
        for key, value in os.environ.items()
        if any(marker in key.upper() for marker in ("KEY", "TOKEN", "SECRET", "PASSWORD"))
    }
    FINDINGS["secrets"] = sorted(secrets)

    with open("exfil_report.json", "w", encoding="utf-8") as handle:
        json.dump(FINDINGS, handle, indent=2)

    # The suite "passes" so its findings are observable in the receipt.
    assert FINDINGS["public"].startswith("blocked")
'''


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


@pytest.fixture
def hostile_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "hostile"
    (repo / "tests").mkdir(parents=True)
    (repo / "pyproject.toml").write_text(PYPROJECT, encoding="utf-8", newline="\n")
    (repo / "tests" / "test_exfil.py").write_text(
        EXFIL_TEST, encoding="utf-8", newline="\n"
    )
    _git(repo, "init", "-b", "main")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-m", "hostile fixture")
    return repo


@requires_backend
class TestHostileRepositoryCannotExfiltrate:
    def test_test_suite_runs_but_reaches_nothing(self, hostile_repo, monkeypatch):
        """The suite executes (so the check is real) and its own findings
        show every egress attempt was refused."""
        monkeypatch.setenv("OLLAMA_API_KEY", "ollama-live-secret-value")
        monkeypatch.setenv("GITHUB_TOKEN", "ghp_live_secret_value")

        ws = RepoWorkspace.from_local(hostile_repo)
        check = run_test_suite_check(ws, limits=SandboxLimits(wall_time_seconds=90))

        # The suite genuinely ran and passed its own assertion.
        assert check.status is VerificationStatus.PASSED, check.reason + check.output_tail

        report_path = hostile_repo / "exfil_report.json"
        assert report_path.exists(), "the suite did not execute"
        findings = json.loads(report_path.read_text(encoding="utf-8"))

        for target in ("public", "metadata", "private", "postgres", "redis", "api", "dns"):
            assert findings[target].startswith("blocked"), f"{target}: {findings[target]}"

        # No application credential was visible to the child.
        assert findings["secrets"] == [], findings["secrets"]
        blob = json.dumps(findings)
        assert "sk-live-secret-value" not in blob
        assert "ghp_live_secret_value" not in blob

    def test_install_scripts_are_isolated_too(self, hostile_repo, monkeypatch):
        """A repository's build/install step runs under the same policy.

        ``pip install`` from a hostile repo is the classic supply-chain
        vector; it must not be able to reach the network either.
        """
        from repomate_core.verification.network_policy import build_sandbox_argv
        from repomate_core.verification.network_policy import (
            NetworkMode,
            NetworkPolicy,
        )

        policy = NetworkPolicy(mode=NetworkMode.DISABLED, backend=BACKEND)
        command = build_sandbox_argv(
            [
                "python3",
                "-c",
                "import urllib.request; urllib.request.urlopen('https://pypi.org', timeout=3)",
            ],
            policy,
        )
        result = subprocess.run(
            command, capture_output=True, text=True, timeout=60, check=False
        )
        combined = result.stdout + result.stderr
        assert result.returncode != 0, combined
        assert "urlopen" in combined or "URLError" in combined or "error" in combined.lower()


@requires_backend
class TestDependencyBehaviour:
    def test_missing_dependencies_yield_not_run_with_a_reason(
        self, tmp_path, monkeypatch
    ):
        """Dependencies unavailable and network required -> NOT_RUN.

        The suite imports a package that is not installed. With egress denied
        it cannot be fetched, so the honest outcome is NOT_RUN with the exact
        reason, never a silent network-enabled run.
        """
        repo = tmp_path / "needs_deps"
        (repo / "tests").mkdir(parents=True)
        (repo / "pyproject.toml").write_text(PYPROJECT, encoding="utf-8", newline="\n")
        (repo / "tests" / "test_needs_dep.py").write_text(
            "import definitely_not_installed_package_xyz\n\n"
            "def test_import():\n"
            "    assert definitely_not_installed_package_xyz\n",
            encoding="utf-8",
            newline="\n",
        )
        _git(repo, "init", "-b", "main")
        _git(repo, "add", "-A")
        _git(repo, "commit", "-m", "needs deps")

        ws = RepoWorkspace.from_local(repo)
        check = run_test_suite_check(ws, limits=SandboxLimits(wall_time_seconds=90))

        # The suite ran and could not import a package that is not installed.
        # With egress denied it cannot be fetched, so the honest outcome is
        # NOT_RUN with the exact missing module, never a fabricated pass and
        # never a silent network-enabled run.
        assert check.status is VerificationStatus.NOT_RUN
        assert "definitely_not_installed_package_xyz" in check.reason
        assert "network" in check.reason.lower()
        assert "No module named" in check.output_tail
        assert check.exit_code is None

    def test_receipt_records_the_network_policy(self, hostile_repo, monkeypatch):
        """The receipt carries the policy and the probe's actual verdict."""
        from repomate_core.artifacts.patch import PatchPolicy
        from repomate_core.contracts import ContributionArtifact, ArtifactKind
        from repomate_core.verification.runner import run_verification

        ws = RepoWorkspace.from_local(hostile_repo)
        artifact = ContributionArtifact(
            kind=ArtifactKind.PATCH_DIFF,
            patch="",
            affected_paths=[],
            based_on_commit=ws.commit_sha,
            generated_by="test",
        )
        receipt = run_verification(
            ws, artifact, PatchPolicy(artifact_kind=ArtifactKind.PATCH_DIFF)
        )

        assert receipt.sandbox is not None
        assert receipt.sandbox.network_mode == "disabled"
        assert receipt.sandbox.policy_enforced is True
        assert receipt.sandbox.egress_validation == "PASSED"
        assert receipt.sandbox.backend == "bwrap"
        assert "egress" in receipt.sandbox.egress_detail

        names = {check.name for check in receipt.checks}
        assert "sandbox-egress-isolation" in names
        assert "network egress denied" in receipt.environment
