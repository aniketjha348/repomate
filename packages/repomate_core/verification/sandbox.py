"""Disposable verification sandbox — process backend.

Untrusted repository test commands run through :class:`ProcessSandbox`,
never bare on the host:

- **network egress denied**: the command runs inside an unprivileged Linux
  network namespace (``bwrap --unshare-net``), verified by a live probe
  before the command is allowed to run. If no enforcing backend exists on
  this host the sandbox **refuses to execute** rather than running with
  network access — see :mod:`repomate_core.verification.network_policy`.
- **wall-time kill**: the process tree is killed on timeout (SIGKILL to the
  process group on POSIX, ``taskkill /T /F`` on Windows)
- **CPU budget**: ``RLIMIT_CPU`` stops runaway compute (POSIX)
- **memory budget**: ``RLIMIT_AS`` turns runaway allocation into failure
  (POSIX)
- **file-size budget**: ``RLIMIT_FSIZE`` caps writes (POSIX)
- **environment scrubbing**: only an explicit allowlist (PATH/HOME/locale
  plus Windows system variables) reaches the child — server secrets
  (model keys, tokens) never do
- **bounded outputs**: stdout/stderr are tailed to a fixed size

Honest limitations (documented in docs/security.md): the process backend
isolates the network, narrows the filesystem and gives the sandbox its own
process table, but it is not a full VM; the host kernel is shared.
``RLIMIT_NPROC`` is deliberately not used because it is per-UID and would
break the host session. On Windows the ``resource`` module is unavailable
and no network namespace exists, so the sandbox refuses to execute
repository commands at all unless the operator explicitly sets
``REPOMATE_SANDBOX_NETWORK=host`` (which the receipt records).
"""


from __future__ import annotations

import json
import os
import re
import shutil
import signal
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Sequence

from repomate_core.contracts import VerificationCheck, VerificationStatus
from repomate_core.repository.workspace import RepoWorkspace
from repomate_core.verification.network_policy import (
    NetworkMode,
    NetworkPolicy,
    build_sandbox_argv,
    probe_egress_isolation,
    resolve_network_policy,
)

try:  # POSIX-only module; Windows has no ``resource``.
    import resource
except ImportError:  # pragma: no cover - exercised on Windows
    resource = None  # type: ignore[assignment]

_IS_POSIX = os.name == "posix"
_ENV_ALLOWLIST = (
    "PATH",
    "HOME",
    "USERPROFILE",
    "LANG",
    "LC_ALL",
    "TMPDIR",
    "TMP",
    "TEMP",
    "SYSTEMROOT",
    "WINDIR",
    "COMSPEC",
    "PATHEXT",
)
_OUTPUT_TAIL_CHARS = 2000

# The adversarial probe: every one of these must be refused from inside the
# sandbox. A single "reachable" verdict fails the check. It runs with
# ``python -I`` in an empty directory (see run_egress_probe_check), so
# repository files cannot shadow the modules it imports.
_EGRESS_PROBE_MARKER = "REPOMATE_EGRESS_MATRIX "
_EGRESS_PROBE_TARGETS = {
    "public_http": ("1.1.1.1", 80),
    "public_https": ("example.com", 443),
    "cloud_metadata": ("169.254.169.254", 80),
    "cloud_metadata_ipv6": ("fd00:ec2::254", 80),
    "private_rfc1918_10": ("10.0.0.1", 80),
    "private_rfc1918_172": ("172.16.0.1", 80),
    "private_rfc1918_192": ("192.168.0.1", 80),
    "loopback_postgres": ("127.0.0.1", 5432),
    "loopback_redis": ("127.0.0.1", 6379),
    "loopback_api": ("127.0.0.1", 8000),
    "dns": None,
}
_EGRESS_PROBE_SCRIPT = f'''
import http.client, json, socket

targets = {{
    "public_http": ("1.1.1.1", 80),
    "cloud_metadata": ("169.254.169.254", 80),
    "cloud_metadata_ipv6": ("fd00:ec2::254", 80),
    "private_rfc1918_10": ("10.0.0.1", 80),
    "private_rfc1918_172": ("172.16.0.1", 80),
    "private_rfc1918_192": ("192.168.0.1", 80),
    "loopback_postgres": ("127.0.0.1", 5432),
    "loopback_redis": ("127.0.0.1", 6379),
    "loopback_api": ("127.0.0.1", 8000),
}}
result = {{}}
for name, (host, port) in targets.items():
    try:
        sock = socket.create_connection((host, port), timeout=2)
        sock.close()
        result[name] = "reachable"
    except Exception as exc:
        result[name] = "blocked:" + type(exc).__name__
try:
    connection = http.client.HTTPSConnection("example.com", 443, timeout=2)
    connection.connect()
    connection.close()
    result["public_https"] = "reachable"
except Exception as exc:
    result["public_https"] = "blocked:" + type(exc).__name__
try:
    socket.gethostbyname("example.com")
    result["dns"] = "reachable"
except Exception as exc:
    result["dns"] = "blocked:" + type(exc).__name__
print({_EGRESS_PROBE_MARKER!r} + json.dumps(result))
'''


@dataclass(frozen=True)
class SandboxLimits:
    wall_time_seconds: int = 120
    cpu_seconds: int = 60
    memory_mb: int = 512


@dataclass(frozen=True)
class ToolchainCommand:
    name: str
    argv: tuple[str, ...]
    display: str


@dataclass(frozen=True)
class SandboxResult:
    exit_code: Optional[int]
    stdout_tail: str
    stderr_tail: str
    timed_out: bool = False
    killed_reason: str = ""
    # Egress policy actually applied, and what the probe observed.
    network_policy: Optional[NetworkPolicy] = None
    egress_validation: str = "NOT_RUN"
    egress_detail: str = ""


def _tail(text: str) -> str:
    return text[-_OUTPUT_TAIL_CHARS:] if len(text) > _OUTPUT_TAIL_CHARS else text


def _apply_limits(limits: SandboxLimits):
    if resource is None or not _IS_POSIX:
        return None

    def preexec() -> None:
        os.setsid()
        cpu = limits.cpu_seconds
        resource.setrlimit(resource.RLIMIT_CPU, (cpu, cpu + 1))
        mem = limits.memory_mb * 1024 * 1024
        resource.setrlimit(resource.RLIMIT_AS, (mem, mem))
        file_cap = 64 * 1024 * 1024
        resource.setrlimit(resource.RLIMIT_FSIZE, (file_cap, file_cap))

    return preexec


def _sandbox_env(policy: NetworkPolicy) -> dict[str, str]:
    """The only environment untrusted repository code ever sees.

    Secrets are never on the allowlist. Under an enforced policy, HOME and
    temp directories point into the sandbox's private tmpfs and PATH is
    rebuilt from the interpreter and system bin directories, so host paths
    (and a host home directory that happens to contain credentials) are not
    handed to the child even as strings.
    """
    env = {key: os.environ[key] for key in _ENV_ALLOWLIST if key in os.environ}
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    if policy.enforced:
        env["HOME"] = "/tmp"
        env["TMPDIR"] = "/tmp"
        env["TMP"] = "/tmp"
        env["TEMP"] = "/tmp"
        interpreter_bin = str(Path(sys.executable).parent)
        path_entries = [interpreter_bin, "/usr/local/bin", "/usr/bin", "/bin"]
        deduped: list[str] = []
        for entry in path_entries:
            if entry and entry not in deduped:
                deduped.append(entry)
        env["PATH"] = os.pathsep.join(deduped)
    return env


class ProcessSandbox:
    def __init__(
        self, limits: SandboxLimits, *, policy: Optional[NetworkPolicy] = None
    ) -> None:
        self.limits = limits
        self.policy = policy or resolve_network_policy()

    def run(self, argv: Sequence[str], cwd: Path) -> SandboxResult:
        # Fail closed. Untrusted code runs only under an enforced policy; if
        # the policy cannot be enforced, refusing to run is the honest
        # outcome. Running it with network access would be a silent
        # downgrade of a security control.
        refusal = self.policy.refusal_reason()
        if refusal:
            return SandboxResult(
                None,
                "",
                refusal,
                network_policy=self.policy,
                egress_validation="NOT_ENFORCED",
                egress_detail=refusal,
            )

        # Verify the boundary before trusting it. The probe runs the same
        # wrapped command the repository will run, but in a fresh empty
        # directory: the repository under test must not be able to shadow
        # ``socket``/``json`` or plant ``sitecustomize.py`` and fake its own
        # admission check. A backend that is present but non-functional (a
        # kernel that forbids user namespaces, a container policy that
        # overrides it) is caught here rather than assumed away.
        isolated, detail = probe_egress_isolation(self.policy)
        if self.policy.blocks_egress and not isolated:
            reason = f"egress isolation could not be verified: {detail}"
            return SandboxResult(
                None,
                "",
                reason,
                network_policy=self.policy,
                egress_validation="FAILED",
                egress_detail=detail,
            )
        egress_validation = "PASSED" if isolated else "NOT_ENFORCED"

        env = _sandbox_env(self.policy)
        wrapped = build_sandbox_argv(argv, self.policy, workspace=cwd)
        popen_kwargs: dict = {
            "cwd": str(cwd),
            "env": env,
            "stdout": subprocess.PIPE,
            "stderr": subprocess.PIPE,
            "text": True,
            "encoding": "utf-8",
            "errors": "replace",
        }
        if _IS_POSIX:
            popen_kwargs["preexec_fn"] = _apply_limits(self.limits)
        else:
            # Windows has no preexec_fn; a new process group lets taskkill
            # terminate the whole tree (pytest may spawn workers).
            popen_kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP
        try:
            process = subprocess.Popen([str(a) for a in wrapped], **popen_kwargs)
        except OSError as exc:
            return SandboxResult(
                None,
                "",
                f"failed to start: {exc}",
                network_policy=self.policy,
                egress_validation=egress_validation,
                egress_detail=detail,
            )

        try:
            stdout, stderr = process.communicate(timeout=self.limits.wall_time_seconds)
        except subprocess.TimeoutExpired:
            _kill_process_group(process)
            try:
                stdout, stderr = process.communicate(timeout=10)
            except subprocess.TimeoutExpired:
                process.kill()
                stdout, stderr = process.communicate()
            reason = f"test suite exceeded the {self.limits.wall_time_seconds}s wall-time budget and was killed"
            return SandboxResult(
                None,
                _tail(stdout),
                _tail(stderr),
                timed_out=True,
                killed_reason=reason,
                network_policy=self.policy,
                egress_validation=egress_validation,
                egress_detail=detail,
            )
        return SandboxResult(
            process.returncode,
            _tail(stdout),
            _tail(stderr),
            network_policy=self.policy,
            egress_validation=egress_validation,
            egress_detail=detail,
        )


def _kill_process_group(process: subprocess.Popen) -> None:
    if _IS_POSIX:
        try:
            os.killpg(os.getpgid(process.pid), signal.SIGKILL)
        except (ProcessLookupError, PermissionError, OSError):
            process.kill()
        return
    # Windows: /T kills the child and all descendants.
    try:
        subprocess.run(
            ["taskkill", "/F", "/T", "/PID", str(process.pid)],
            capture_output=True,
            timeout=10,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        process.kill()


def sandbox_environment_description(policy: Optional[NetworkPolicy] = None) -> str:
    """Human-readable, honest description of the active sandbox limits."""
    active = policy or resolve_network_policy()
    if active.mode is NetworkMode.DISABLED:
        network = (
            f"network egress denied ({active.backend.value})"
            if active.backend.value != "none"
            else "network egress required but NOT ENFORCEABLE on this host"
        )
    else:
        network = "network egress PERMITTED by operator configuration"

    if _IS_POSIX:
        return f"process sandbox (wall-time, CPU and memory limits, scrubbed env; {network})"
    return (
        "process sandbox (wall-time kill, scrubbed env; "
        f"CPU/memory limits unavailable on this OS; {network})"
    )


def sandbox_limitations(policy: Optional[NetworkPolicy] = None) -> list[str]:
    """Platform-specific limitations included in every receipt."""
    active = policy or resolve_network_policy()
    limitations: list[str] = []

    if active.mode is NetworkMode.HOST:
        limitations.append(
            "Network egress is PERMITTED for sandboxed commands "
            "(REPOMATE_SANDBOX_NETWORK=host); untrusted repository code can reach "
            "the network. Not suitable for public multi-tenant use."
        )
    elif active.backend.value == "none":
        limitations.append(
            "No egress-enforcement backend is available on this host, so "
            "repository test commands are refused rather than run with network "
            "access."
        )
    else:
        limitations.append(
            "The sandbox uses an unprivileged bwrap namespace: egress is denied, "
            "host socket directories are masked, the process table is private, "
            "and the repository's .git directory is read-only. It is not a full "
            "VM; the host kernel is shared."
        )

    limitations.append(
        "Repository tests run with RepoMate's interpreter and installed "
        "dependencies; a repo-specific virtualenv is not created, so missing "
        "dependencies are reported NOT_RUN (they cannot be downloaded without "
        "network access)."
    )
    if not _IS_POSIX:
        limitations.append(
            "CPU, memory and file-size rlimits are POSIX-only; on Windows the "
            "sandbox enforces only the wall-time budget and environment scrubbing."
        )
    return limitations


def detect_test_command(ws: RepoWorkspace) -> Optional[ToolchainCommand]:
    """Recognize a permitted test command for the repository.

    MVP allowlist: pytest (via the interpreter RepoMate itself runs on)
    and make. Node toolchains are intentionally excluded from the process
    backend (they resolve to host-global binaries); they arrive with the
    container backend.
    """
    files = ws.ls_files()
    has_tests = any(
        f.startswith("tests/") or f.startswith("test/") or f.startswith("src/tests/")
        for f in files
    ) or any(Path(f).name.startswith("test_") for f in files)

    if "pyproject.toml" in files and has_tests:
        return ToolchainCommand(
            name="pytest",
            argv=(sys.executable, "-m", "pytest", "-q"),
            display="python -m pytest -q",
        )

    if "Makefile" in files and _makefile_targets(ws, "Makefile") & {"test", "check"}:
        if shutil.which("make"):
            return ToolchainCommand("make", ("make", "test"), "make test")

    return None


def _makefile_targets(ws: RepoWorkspace, path: str) -> set[str]:
    try:
        content = ws.read_text(path, max_chars=100_000)
    except Exception:
        return set()
    targets = set()
    for line in content.splitlines():
        if line.startswith("\t") or line.startswith("#") or ":" not in line:
            continue
        targets.add(line.split(":", 1)[0].strip())
    return targets


def run_test_suite_check(
    ws: RepoWorkspace,
    *,
    limits: Optional[SandboxLimits] = None,
    policy: Optional[NetworkPolicy] = None,
    command: Optional[ToolchainCommand] = None,
) -> VerificationCheck:
    """Execute the repository test suite inside the sandbox, or report an
    honest NOT_RUN when no supported toolchain exists or the sandbox cannot
    enforce its policy.

    ``command`` lets the verification runner detect the toolchain once and
    execute the exact same argv in the baseline and patched workspaces.
    """
    if command is None:
        command = detect_test_command(ws)
    if command is None:
        return VerificationCheck(
            name="repository-test-suite",
            command=None,
            status=VerificationStatus.NOT_RUN,
            reason=(
                "no recognized test command for this repository "
                "(process sandbox supports pytest and make)"
            ),
        )

    sandbox = ProcessSandbox(limits or SandboxLimits(), policy=policy)
    started = time.monotonic()
    result = sandbox.run(command.argv, cwd=ws.root)
    duration_ms = max(0, int((time.monotonic() - started) * 1000))
    combined = (result.stdout_tail + "\n" + result.stderr_tail).strip()[:2000]

    # A refused or unverified boundary is NOT_RUN, never PASSED or FAILED:
    # the suite did not run, and saying otherwise would be a fabricated
    # result. The reason names the exact policy failure.
    if result.egress_validation in ("NOT_ENFORCED", "FAILED"):
        return VerificationCheck(
            name="repository-test-suite",
            command=command.display,
            status=VerificationStatus.NOT_RUN,
            duration_ms=duration_ms,
            reason=(
                "sandbox network policy could not be enforced, so the test suite "
                f"was not executed: {result.egress_detail or result.stderr_tail}"
            ),
            output_tail=combined,
        )

    if result.timed_out:
        return VerificationCheck(
            name="repository-test-suite",
            command=command.display,
            status=VerificationStatus.FAILED,
            duration_ms=duration_ms,
            reason=result.killed_reason,
            output_tail=combined,
        )

    # Dependencies cannot be downloaded with egress denied. A collection
    # failure caused by a missing package is therefore NOT_RUN with the exact
    # module name, not a FAILED suite that implies the repository's code is
    # broken. A real test assertion still reports FAILED.
    if result.exit_code != 0:
        dependency_reason = _dependency_failure_reason(combined)
        if dependency_reason:
            return VerificationCheck(
                name="repository-test-suite",
                command=command.display,
                status=VerificationStatus.NOT_RUN,
                duration_ms=duration_ms,
                reason=dependency_reason,
                output_tail=combined,
            )

    status = VerificationStatus.PASSED if result.exit_code == 0 else VerificationStatus.FAILED
    return VerificationCheck(
        name="repository-test-suite",
        command=command.display,
        status=status,
        exit_code=result.exit_code,
        duration_ms=duration_ms,
        output_tail=combined,
    )


_MISSING_MODULE_RE = re.compile(
    r"(?:ModuleNotFoundError|ImportError): No module named ['\"]?([A-Za-z0-9_.\-]+)"
)
# Pip-specific resolution failures are unambiguous: they can only come from
# a package installer.
_PIP_RESOLUTION_MARKERS = (
    "Could not find a version that satisfies the requirement",
    "No matching distribution found for",
)
# Transport failures can also be raised by the repository's own tests (for
# example, a test that tries to reach the network). Only treat them as a
# dependency-install failure when the surrounding output is pip's.
_PIP_TRANSPORT_MARKERS = (
    "Temporary failure in name resolution",
    "Failed to establish a new connection",
)
_PIP_CONTEXT_MARKERS = (
    "ERROR: Could not install packages",
    "Installing build dependencies",
    "Getting requirements to build wheel",
    "Preparing metadata",
    "pip install",
    "pip's dependency resolver",
)


def _dependency_failure_reason(output: str) -> Optional[str]:
    """Explain a suite that could not start because a dependency is absent.

    The sandbox has no network, so the only honest outcome is NOT_RUN with
    the missing module named. This deliberately matches dependency import
    errors and pip resolution failures, not ordinary test assertions or
    arbitrary network errors raised by the repository's own code. A bare
    ``Temporary failure in name resolution`` from a test is a test failure,
    not a missing dependency; it needs pip context to be classified here.
    """
    match = _MISSING_MODULE_RE.search(output)
    if match:
        module = match.group(1)
        return (
            "required test dependency is unavailable inside the network-disabled "
            f"sandbox: No module named '{module}'. Installing it would require "
            "network access, which the sandbox denies."
        )
    if any(marker in output for marker in _PIP_RESOLUTION_MARKERS):
        return (
            "dependency installation failed because the sandbox has no network "
            "access (package resolution failed)"
        )
    if any(marker in output for marker in _PIP_TRANSPORT_MARKERS) and any(
        context in output for context in _PIP_CONTEXT_MARKERS
    ):
        marker = next(
            marker for marker in _PIP_TRANSPORT_MARKERS if marker in output
        )
        return (
            "dependency installation failed because the sandbox has no network "
            f"access ({marker})"
        )
    return None


def run_egress_probe_check(
    *, limits: Optional[SandboxLimits] = None, policy: Optional[NetworkPolicy] = None
) -> VerificationCheck:
    """Prove the sandbox boundary against live connection attempts.

    This is the check that justifies ``egress_validation: PASSED`` in a
    receipt. It runs real connection attempts from inside the sandbox — to a
    public address, a cloud metadata endpoint, a private address, loopback,
    and a DNS resolver — and passes only when every one is refused.
    """
    active = policy or resolve_network_policy()
    if active.mode is NetworkMode.HOST:
        return VerificationCheck(
            name="sandbox-egress-isolation",
            command=None,
            status=VerificationStatus.NOT_RUN,
            reason=(
                "network egress is permitted by configuration "
                "(REPOMATE_SANDBOX_NETWORK=host), so isolation cannot be validated"
            ),
        )
    if active.backend.value == "none":
        return VerificationCheck(
            name="sandbox-egress-isolation",
            command=None,
            status=VerificationStatus.NOT_RUN,
            reason=active.refusal_reason(),
        )

    # Empty directory + ``-I``: the repository under test is not mounted and
    # cannot shadow modules or plant a ``sitecustomize.py`` that fakes the
    # verdict. The probe must be independent of the code it is protecting us
    # from.
    with tempfile.TemporaryDirectory(prefix="repomate-egress-check-") as probe_dir:
        sandbox = ProcessSandbox(limits or SandboxLimits(), policy=active)
        result = sandbox.run(
            [sys.executable, "-I", "-c", _EGRESS_PROBE_SCRIPT],
            cwd=Path(probe_dir),
        )

    if result.egress_validation in ("FAILED", "NOT_ENFORCED"):
        return VerificationCheck(
            name="sandbox-egress-isolation",
            command="internal:egress-probe",
            status=VerificationStatus.FAILED,
            reason=result.egress_detail or "the sandbox could not run the egress probe",
            output_tail=(result.stdout_tail + "\n" + result.stderr_tail).strip()[:800],
        )

    verdict = _parse_egress_probe(result.stdout_tail)
    if verdict is None:
        return VerificationCheck(
            name="sandbox-egress-isolation",
            command="internal:egress-probe",
            status=VerificationStatus.FAILED,
            reason="the egress probe produced no verdict inside the sandbox",
            output_tail=(result.stdout_tail + "\n" + result.stderr_tail).strip()[:800],
        )

    missing = sorted(set(_EGRESS_PROBE_TARGETS) - set(verdict))
    if missing:
        return VerificationCheck(
            name="sandbox-egress-isolation",
            command="internal:egress-probe",
            status=VerificationStatus.FAILED,
            reason=f"the egress probe did not test: {', '.join(missing)}",
            output_tail=json.dumps(verdict, indent=2)[:800],
        )

    reachable = [name for name, state in verdict.items() if not str(state).startswith("blocked")]
    if reachable:
        return VerificationCheck(
            name="sandbox-egress-isolation",
            command="internal:egress-probe",
            status=VerificationStatus.FAILED,
            reason=f"egress reached from inside the sandbox: {', '.join(sorted(reachable))}",
            output_tail=json.dumps(verdict, indent=2)[:800],
        )
    return VerificationCheck(
        name="sandbox-egress-isolation",
        command="internal:egress-probe",
        status=VerificationStatus.PASSED,
        reason="every egress attempt from inside the sandbox was refused",
        output_tail=json.dumps(verdict, indent=2)[:800],
    )


def _parse_egress_probe(stdout: str) -> Optional[dict]:
    for line in stdout.splitlines():
        if line.startswith(_EGRESS_PROBE_MARKER):
            try:
                return json.loads(line[len(_EGRESS_PROBE_MARKER):])
            except json.JSONDecodeError:
                return None
    return None
