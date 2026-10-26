"""Adversarial acceptance tests for sandbox egress isolation.

These run against the **real sandbox boundary**, not a mocked policy
function. Each test executes an actual connection attempt from inside the
sandbox and asserts on what happened.

The invariant: untrusted repository code and its test suite cannot reach the
network, internal services, cloud metadata, or application secrets.

Honest scope note: the tests that require an enforcing backend are skipped
when the host has none (Windows, or a kernel that forbids unprivileged user
namespaces). They are *not* skipped silently in the product — the sandbox
refuses to execute at all in that case, which
``test_missing_backend_refuses_to_execute`` asserts directly.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from repomate_core.contracts import VerificationStatus
from repomate_core.verification.network_policy import (
    EgressBackend,
    NetworkMode,
    NetworkPolicy,
    build_sandbox_argv,
    detect_egress_backend,
    network_policy_record,
    probe_egress_isolation,
    resolve_network_policy,
)
from repomate_core.verification.sandbox import (
    ProcessSandbox,
    SandboxLimits,
    run_egress_probe_check,
    run_test_suite_check,
)

pytestmark = pytest.mark.skipif(
    os.name != "posix",
    reason="network namespaces are a POSIX/Linux mechanism",
)

BACKEND = detect_egress_backend()
requires_backend = pytest.mark.skipif(
    BACKEND is EgressBackend.NONE,
    reason="no egress-enforcement backend on this host (bwrap/unshare)",
)


def _default_policy() -> NetworkPolicy:
    return NetworkPolicy(mode=NetworkMode.DISABLED, backend=BACKEND)


def _run_in_sandbox(script: str, *, timeout: int = 60) -> subprocess.CompletedProcess:
    """Execute a Python snippet inside the real sandbox boundary."""
    policy = _default_policy()
    command = build_sandbox_argv([sys.executable, "-c", script], policy)
    return subprocess.run(
        command,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout,
        check=False,
    )


# -- the boundary itself ------------------------------------------------------


@requires_backend
class TestNegativeControl:
    """Prove the tests above are meaningful.

    Without this, a broken probe (a typo in the target, a sandbox that
    refuses to start) would make every isolation assertion pass vacuously.
    The same connection attempt must SUCCEED when the wrapper is removed.
    """

    def test_the_same_probe_reaches_the_network_without_the_sandbox(self):
        script = (
            "import socket\n"
            "try:\n"
            "    s = socket.create_connection(('1.1.1.1', 80), timeout=5)\n"
            "    s.close(); print('REACHABLE')\n"
            "except Exception as e:\n"
            "    print('BLOCKED', type(e).__name__)\n"
        )
        unwrapped = subprocess.run(
            [sys.executable, "-c", script],
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
        # If this host has no egress at all, the control is inconclusive
        # rather than failing: the isolation tests still hold, they are just
        # not distinguishing anything on this machine.
        if "BLOCKED" in unwrapped.stdout:
            pytest.skip(
                "this host has no outbound network, so the negative control "
                "cannot distinguish isolated from unisolated"
            )
        assert "REACHABLE" in unwrapped.stdout, unwrapped.stdout + unwrapped.stderr

    def test_dns_resolves_without_the_sandbox(self):
        unwrapped = subprocess.run(
            [sys.executable, "-c", "import socket; print(socket.gethostbyname('example.com'))"],
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
        if unwrapped.returncode != 0:
            pytest.skip("this host has no DNS resolution available")
        assert unwrapped.stdout.strip(), "expected a resolved address"


# -- escape routes the network namespace does NOT cover ----------------------


@requires_backend
class TestFilesystemEscapeRoutes:
    """A network namespace blocks IP egress. It does NOT block unix domain
    sockets, and an early version of this wrapper used ``--dev-bind / /``,
    which exposed the whole host filesystem.

    That was a real escape route: a hostile suite connected to a host control
    socket from inside the sandbox and drove it. These tests are the
    regression guard.
    """

    def test_host_unix_control_socket_is_unreachable(self, tmp_path):
        """Create a real listening unix socket and try to drive it."""
        import socket
        import threading

        sock_path = str(tmp_path / "control.sock")
        server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        server.bind(sock_path)
        server.listen(2)
        os.chmod(sock_path, 0o777)

        received: list[str] = []

        def serve() -> None:
            server.settimeout(5)
            try:
                conn, _ = server.accept()
                received.append(conn.recv(128).decode("utf-8", "replace"))
                conn.close()
            except Exception as exc:
                received.append(f"no connection ({type(exc).__name__})")

        thread = threading.Thread(target=serve, daemon=True)
        thread.start()
        try:
            result = _run_in_sandbox(
                "import socket\n"
                f"path = {sock_path!r}\n"
                "try:\n"
                "    s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)\n"
                "    s.settimeout(3)\n"
                "    s.connect(path)\n"
                "    s.sendall(b'DRIVE-CONTROL-PLANE')\n"
                "    print('CONNECTED')\n"
                "except Exception as e:\n"
                "    print('BLOCKED', type(e).__name__)\n"
            )
            thread.join(timeout=7)
        finally:
            server.close()

        assert "CONNECTED" not in result.stdout, result.stdout
        assert "BLOCKED" in result.stdout, result.stdout
        # The host socket must not have been driven.
        assert received and received[0].startswith("no connection"), received

    def test_host_socket_directories_are_masked(self):
        """The directories that carry control sockets are empty inside."""
        result = _run_in_sandbox(
            "import os, json\n"
            "out = {}\n"
            "for path in ['/run', '/var/run', '/var/tmp', '/dev/shm']:\n"
            "    try:\n"
            "        out[path] = sorted(os.listdir(path))[:5]\n"
            "    except Exception as e:\n"
            "        out[path] = 'error:' + type(e).__name__\n"
            "print('DIRS ' + json.dumps(out))\n"
        )
        line = next(
            (l for l in result.stdout.splitlines() if l.startswith("DIRS")), ""
        )
        assert line, result.stdout + result.stderr
        listing = json.loads(line[len("DIRS"):])
        for path, entries in listing.items():
            assert entries == [], f"{path} is not masked: {entries}"

    def test_host_home_and_project_tree_are_invisible(self):
        """The sandbox sees the repository under test, not the host's files."""
        result = _run_in_sandbox(
            "import os, json\n"
            "out = {}\n"
            "for path in ['/root', '/home', '/mnt/d/repomate/.env', '/etc/shadow']:\n"
            "    out[path] = os.path.exists(path)\n"
            "print('VIS ' + json.dumps(out))\n"
        )
        line = next((l for l in result.stdout.splitlines() if l.startswith("VIS")), "")
        assert line, result.stdout + result.stderr
        visible = json.loads(line[len("VIS"):])
        # /etc is mounted read-only for the toolchain, but the host's secret
        # files must not be readable, and the host project tree must be gone.
        assert visible["/mnt/d/repomate/.env"] is False, visible
        assert visible["/root"] is False, visible

    def test_proc_is_synthesized_not_the_hosts(self):
        """The sandbox sees its own process table, not the host's.

        Without ``--unshare-pid`` a fresh procfs still enumerated every host
        process (33 on this machine). With it, only the sandbox's own
        processes appear, and ``/proc/1`` is the sandbox's init — not the
        host's PID 1.
        """
        result = _run_in_sandbox(
            "import os\n"
            "print('PIDMAX', len([p for p in os.listdir('/proc') if p.isdigit()]))\n"
            "print('HOSTINIT', os.path.exists('/proc/1/environ'))\n"
        )
        count_line = next(
            (l for l in result.stdout.splitlines() if l.startswith("PIDMAX")), ""
        )
        assert count_line, result.stdout + result.stderr
        visible = int(count_line.split()[1])
        # A synthesized procfs shows only the sandbox's own processes; the
        # host had 33 at the time this was written.
        assert visible < 10, f"host process table leaked: {visible} PIDs visible"

    def test_host_process_table_is_not_enumerable(self):
        """The host's PIDs must not be visible, whatever their count."""
        host_pids = len(
            [p for p in os.listdir("/proc") if p.isdigit()]
        )
        result = _run_in_sandbox(
            "import os\n"
            "print('SANDBOXPIDS', len([p for p in os.listdir('/proc') if p.isdigit()]))\n"
        )
        line = next(
            (l for l in result.stdout.splitlines() if l.startswith("SANDBOXPIDS")), ""
        )
        assert line, result.stdout + result.stderr
        sandbox_pids = int(line.split()[1])
        assert sandbox_pids < host_pids, (
            f"sandbox sees {sandbox_pids} PIDs, host has {host_pids}: no PID namespace"
        )


@requires_backend
class TestEgressIsolationBoundary:
    def test_public_http_is_blocked(self):
        """Test script contacts https://example.com — connection blocked."""
        result = _run_in_sandbox(
            "import urllib.request\n"
            "try:\n"
            "    urllib.request.urlopen('https://example.com', timeout=5)\n"
            "    print('REACHABLE')\n"
            "except Exception as e:\n"
            "    print('BLOCKED', type(e).__name__)\n"
        )
        assert "REACHABLE" not in result.stdout, result.stdout
        assert "BLOCKED" in result.stdout, result.stdout

    def test_dns_lookup_is_blocked(self):
        """DNS lookup attempt — blocked, since no resolver is reachable."""
        result = _run_in_sandbox(
            "import socket\n"
            "try:\n"
            "    print('RESOLVED', socket.gethostbyname('example.com'))\n"
            "except Exception as e:\n"
            "    print('BLOCKED', type(e).__name__)\n"
        )
        assert "RESOLVED" not in result.stdout, result.stdout
        assert "BLOCKED" in result.stdout, result.stdout

    def test_cloud_metadata_endpoint_is_blocked(self):
        """169.254.169.254 — the cloud instance metadata service."""
        result = _run_in_sandbox(
            "import socket\n"
            "try:\n"
            "    s = socket.create_connection(('169.254.169.254', 80), timeout=3)\n"
            "    s.close(); print('REACHABLE')\n"
            "except Exception as e:\n"
            "    print('BLOCKED', type(e).__name__)\n"
        )
        assert "REACHABLE" not in result.stdout, result.stdout
        assert "BLOCKED" in result.stdout, result.stdout

    def test_private_network_is_blocked(self):
        """RFC1918 private addresses."""
        for host in ("10.0.0.1", "172.16.0.1", "192.168.0.1"):
            result = _run_in_sandbox(
                "import socket\n"
                f"try:\n"
                f"    s = socket.create_connection(('{host}', 80), timeout=3)\n"
                f"    s.close(); print('REACHABLE')\n"
                f"except Exception as e:\n"
                f"    print('BLOCKED', type(e).__name__)\n"
            )
            assert "REACHABLE" not in result.stdout, f"{host} reachable: {result.stdout}"
            assert "BLOCKED" in result.stdout, result.stdout + result.stderr

    def test_ipv6_cloud_metadata_is_blocked(self):
        """The IPv6 metadata endpoint must be refused too."""
        result = _run_in_sandbox(
            "import socket\n"
            "try:\n"
            "    s = socket.create_connection(('fd00:ec2::254', 80), timeout=3)\n"
            "    s.close(); print('REACHABLE')\n"
            "except Exception as e:\n"
            "    print('BLOCKED', type(e).__name__)\n"
        )
        assert "REACHABLE" not in result.stdout, result.stdout
        assert "BLOCKED" in result.stdout, result.stdout + result.stderr

    def test_internal_services_are_not_reachable(self):
        """PostgreSQL, Redis and the application API on loopback.

        These are the services a compromised run would most want: the run
        store, the queue, and the API that fronts both.
        """
        for port, label in ((5432, "postgres"), (6379, "redis"), (8000, "api")):
            result = _run_in_sandbox(
                "import socket\n"
                f"try:\n"
                f"    s = socket.create_connection(('127.0.0.1', {port}), timeout=3)\n"
                f"    s.close(); print('REACHABLE')\n"
                f"except Exception as e:\n"
                f"    print('BLOCKED', type(e).__name__)\n"
            )
            assert "REACHABLE" not in result.stdout, f"{label} reachable: {result.stdout}"

    def test_no_non_loopback_interface_exists(self):
        """The namespace must not carry a route to the outside world."""
        result = _run_in_sandbox(
            "import socket, fcntl, struct, array\n"
            "names = array.array('B', b'\\0' * 4096)\n"
            "out = fcntl.ioctl(socket.socket(socket.AF_INET, socket.SOCK_DGRAM),"
            " 0x8912, struct.pack('iL', 4096, names.buffer_info()[0]))\n"
            "print('IFACES', out[0] // 40)\n"
        )
        assert "IFACES" in result.stdout, result.stdout
        count = int(result.stdout.split("IFACES")[1].split()[0])
        # Only loopback remains; eth0 is gone.
        assert count <= 1, f"unexpected interfaces inside the sandbox: {count}"

    def test_workspace_without_git_does_not_need_a_git_mount(self, tmp_path):
        """A non-git workspace must not synthesize a mount point.

        The parent directory can be read-only (for example /app in a
        container). Creating ``.git`` there would make ``bwrap`` fail before
        the command runs, even though there is no git metadata to protect.
        """
        command = build_sandbox_argv(
            [sys.executable, "-c", "print('ok')"],
            _default_policy(),
            workspace=tmp_path,
        )
        assert str(tmp_path / ".git") not in command


# -- secrets ------------------------------------------------------------------


@requires_backend
class TestSecretIsolation:
    def test_application_secrets_are_absent(self):
        """A malicious repository cannot read application credentials.

        The sandbox scrubs the environment to an allowlist, so model keys,
        GitHub tokens and database URLs never reach the child.
        """
        os.environ["OLLAMA_API_KEY"] = "sk-should-never-be-visible"
        os.environ["GITHUB_TOKEN"] = "ghp_should_never_be_visible"
        os.environ["REPOMATE_DATABASE_URL"] = "postgresql://user:pw@db.internal/app"
        try:
            sandbox = ProcessSandbox(SandboxLimits(), policy=_default_policy())
            result = sandbox.run(
                [
                    sys.executable,
                    "-c",
                    "import os, json; print('ENV', json.dumps(dict(os.environ)))",
                ],
                cwd=Path.cwd(),
            )
        finally:
            for key in ("OLLAMA_API_KEY", "GITHUB_TOKEN", "REPOMATE_DATABASE_URL"):
                os.environ.pop(key, None)

        blob = result.stdout_tail + result.stderr_tail
        assert "sk-should-never-be-visible" not in blob
        assert "ghp_should_never_be_visible" not in blob
        assert "db.internal" not in blob
        assert "OLLAMA_API_KEY" not in blob
        assert "GITHUB_TOKEN" not in blob

    def test_env_allowlist_is_explicit(self):
        """Only the documented allowlist reaches the child."""
        sandbox = ProcessSandbox(SandboxLimits(), policy=_default_policy())
        result = sandbox.run(
            [sys.executable, "-c", "import os; print('KEYS', sorted(os.environ))"],
            cwd=Path.cwd(),
        )
        keys_line = next(
            (line for line in result.stdout_tail.splitlines() if line.startswith("KEYS")),
            "",
        )
        assert keys_line, result.stdout_tail + result.stderr_tail
        keys = set(json.loads(keys_line[len("KEYS"):].replace("'", '"')))
        assert "PATH" in keys
        assert not {k for k in keys if "KEY" in k or "TOKEN" in k or "SECRET" in k}


# -- policy cannot be overridden ---------------------------------------------


class TestPolicyCannotBeOverridden:
    def test_default_mode_is_disabled(self, monkeypatch):
        monkeypatch.delenv("REPOMATE_SANDBOX_NETWORK", raising=False)
        assert resolve_network_policy().mode is NetworkMode.DISABLED

    def test_arbitrary_env_value_does_not_enable_network(self, monkeypatch):
        """A model or user cannot enable networking by setting a variable."""
        for value in ("1", "true", "yes", "enabled", "network", "any", ""):
            monkeypatch.setenv("REPOMATE_SANDBOX_NETWORK", value)
            assert resolve_network_policy().mode is NetworkMode.DISABLED, value

    def test_only_explicit_host_opt_in_enables_network(self, monkeypatch):
        monkeypatch.setenv("REPOMATE_SANDBOX_NETWORK", "host")
        assert resolve_network_policy().mode is NetworkMode.HOST

    def test_host_mode_is_recorded_as_not_enforced(self, monkeypatch):
        monkeypatch.setenv("REPOMATE_SANDBOX_NETWORK", "host")
        policy = resolve_network_policy()
        assert policy.enforced is False
        assert policy.refusal_reason() == ""

    def test_missing_backend_refuses_to_execute(self):
        """Fail closed: no backend means no execution, not an open run."""
        policy = NetworkPolicy(mode=NetworkMode.DISABLED, backend=EgressBackend.NONE)
        assert policy.enforced is False
        assert policy.refusal_reason()

        sandbox = ProcessSandbox(SandboxLimits(), policy=policy)
        result = sandbox.run(
            [sys.executable, "-c", "print('SHOULD NOT RUN')"], cwd=Path.cwd()
        )
        assert "SHOULD NOT RUN" not in result.stdout_tail
        assert result.exit_code is None
        assert result.egress_validation == "NOT_ENFORCED"
        assert "no enforcing backend" in result.egress_detail

    def test_disabled_mode_without_backend_does_not_run(self):
        """The refusal is not conditional on the mode name."""
        policy = NetworkPolicy(mode=NetworkMode.DISABLED, backend=EgressBackend.NONE)
        sandbox = ProcessSandbox(SandboxLimits(), policy=policy)
        result = sandbox.run([sys.executable, "-c", "print('LEAK')"], cwd=Path.cwd())
        assert "LEAK" not in result.stdout_tail


# -- verification of the boundary --------------------------------------------


@requires_backend
class TestEgressValidation:
    def test_probe_confirms_isolation(self):
        isolated, detail = probe_egress_isolation(_default_policy())
        assert isolated is True, detail
        assert "blocked" in detail

    def test_probe_reports_host_mode_as_not_isolated(self):
        policy = NetworkPolicy(mode=NetworkMode.HOST, backend=BACKEND)
        isolated, detail = probe_egress_isolation(policy)
        assert isolated is False
        assert "host" in detail

    def test_egress_probe_check_passes_under_isolation(self):
        check = run_egress_probe_check(policy=_default_policy())
        assert check.status is VerificationStatus.PASSED, check.reason
        assert check.name == "sandbox-egress-isolation"
        # The check must carry the evidence for its verdict.
        verdict = json.loads(check.output_tail)
        assert verdict["public_http"].startswith("blocked")
        assert verdict["cloud_metadata"].startswith("blocked")
        assert verdict["dns"].startswith("blocked")

    def test_egress_probe_check_is_not_run_in_host_mode(self):
        policy = NetworkPolicy(mode=NetworkMode.HOST, backend=BACKEND)
        check = run_egress_probe_check(policy=policy)
        assert check.status is VerificationStatus.NOT_RUN
        assert "permitted by configuration" in check.reason

    def test_egress_probe_check_is_not_run_without_backend(self):
        policy = NetworkPolicy(mode=NetworkMode.DISABLED, backend=EgressBackend.NONE)
        check = run_egress_probe_check(policy=policy)
        assert check.status is VerificationStatus.NOT_RUN
        assert check.reason


# -- the repository cannot influence its own admission check -----------------


@requires_backend
class TestProbeCannotBeInfluencedByRepository:
    """A hostile repository must not be able to fake the probe.

    The probe imports ``socket``/``json`` from the interpreter and runs with
    ``-I`` in an empty directory. If it ran in the repository, a
    ``sitecustomize.py`` (or a shadowing ``socket.py``) could make every
    connection look blocked and admit the suite with network access.
    """

    def _repo(self, tmp_path, sitecustomize: str):
        import subprocess

        from repomate_core.repository.workspace import RepoWorkspace

        repo = tmp_path / "probe-shadow"
        (repo / "tests").mkdir(parents=True)
        (repo / "pyproject.toml").write_text(
            "[project]\nname='shadow'\nversion='0.1.0'\n", encoding="utf-8"
        )
        (repo / "sitecustomize.py").write_text(sitecustomize, encoding="utf-8")
        (repo / "tests" / "test_ok.py").write_text(
            "def test_ok():\n    assert True\n", encoding="utf-8"
        )
        env = dict(
            os.environ,
            GIT_AUTHOR_NAME="T",
            GIT_AUTHOR_EMAIL="t@t.invalid",
            GIT_COMMITTER_NAME="T",
            GIT_COMMITTER_EMAIL="t@t.invalid",
        )
        for args in (
            ("init", "-b", "main"),
            ("add", "-A"),
            ("commit", "-m", "shadow"),
        ):
            result = subprocess.run(
                ["git", *args], cwd=str(repo), capture_output=True, text=True, env=env
            )
            assert result.returncode == 0, result.stderr
        return RepoWorkspace.from_local(repo)

    def test_sitecustomize_cannot_fake_probe(self, tmp_path, monkeypatch):
        # This module runs for every Python process whose sys.path contains
        # the repository. If the admission probe used the repository as cwd,
        # it would see fake connections that "succeed" and fail the probe.
        ws = self._repo(
            tmp_path,
            "import socket\n"
            "class _Sock:\n"
            "    def close(self):\n"
            "        pass\n"
            "def _fake(*args, **kwargs):\n"
            "    return _Sock()\n"
            "socket.create_connection = _fake\n",
        )
        monkeypatch.chdir(ws.root)

        # The boundary check must still PASS against the real network, and
        # the suite must actually run (not be refused because a fake probe
        # said egress was reachable).
        check = run_egress_probe_check(policy=_default_policy())
        assert check.status is VerificationStatus.PASSED, check.reason
        verdict = json.loads(check.output_tail)
        assert verdict["public_https"].startswith("blocked")

        suite = run_test_suite_check(
            ws, limits=SandboxLimits(wall_time_seconds=60), policy=_default_policy()
        )
        assert suite.status is VerificationStatus.PASSED, suite.reason + suite.output_tail

    def test_git_metadata_is_read_only_inside_the_sandbox(self, tmp_path):
        """A test cannot edit .git/config and poison the host-side reset.

        ``git reset --hard`` after verification honours smudge/filter config;
        if the sandbox could write ``.git/config``, a hostile suite could make
        the host execute it outside the sandbox.
        """
        import subprocess

        from repomate_core.repository.workspace import RepoWorkspace

        repo = tmp_path / "git-protect"
        (repo / "tests").mkdir(parents=True)
        (repo / "pyproject.toml").write_text(
            "[project]\nname='gitp'\nversion='0.1.0'\n", encoding="utf-8"
        )
        (repo / "tests" / "test_git.py").write_text(
            "from pathlib import Path\n\n"
            "def test_git_config_is_read_only():\n"
            "    target = Path('.git/config')\n"
            "    try:\n"
            "        with target.open('a', encoding='utf-8') as handle:\n"
            "            handle.write('\\n[filter \"pwn\"]\\n    smudge = touch /tmp/pwned\\n')\n"
            "    except OSError:\n"
            "        return\n"
            "    raise AssertionError('wrote .git/config from inside the sandbox')\n",
            encoding="utf-8",
        )
        env = dict(
            os.environ,
            GIT_AUTHOR_NAME="T",
            GIT_AUTHOR_EMAIL="t@t.invalid",
            GIT_COMMITTER_NAME="T",
            GIT_COMMITTER_EMAIL="t@t.invalid",
        )
        for args in (
            ("init", "-b", "main"),
            ("add", "-A"),
            ("commit", "-m", "git protect"),
        ):
            run = subprocess.run(
                ["git", *args], cwd=str(repo), capture_output=True, text=True, env=env
            )
            assert run.returncode == 0, run.stderr

        before = (repo / ".git" / "config").read_text(encoding="utf-8")
        ws = RepoWorkspace.from_local(repo)
        check = run_test_suite_check(
            ws, limits=SandboxLimits(wall_time_seconds=60), policy=_default_policy()
        )
        assert check.status is VerificationStatus.PASSED, check.reason + check.output_tail
        after = (repo / ".git" / "config").read_text(encoding="utf-8")
        assert after == before


# -- cross-platform policy tests ---------------------------------------------


class TestPolicyRecord:
    def test_record_is_only_enforced_after_a_passed_probe(self):
        policy = NetworkPolicy(mode=NetworkMode.DISABLED, backend=EgressBackend.BWRAP)
        passed = network_policy_record(policy, egress_validation="PASSED")
        assert passed["policy_enforced"] is True
        for outcome in ("FAILED", "NOT_RUN", "NOT_ENFORCED"):
            record = network_policy_record(policy, egress_validation=outcome)
            assert record["policy_enforced"] is False, outcome

    def test_host_mode_is_never_recorded_as_enforced(self):
        policy = NetworkPolicy(mode=NetworkMode.HOST, backend=EgressBackend.BWRAP)
        record = network_policy_record(policy, egress_validation="PASSED")
        assert record["network_mode"] == "host"
        assert record["policy_enforced"] is False
