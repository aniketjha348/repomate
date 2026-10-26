"""Disposable verification sandbox — process backend.

Untrusted repository test commands run through :class:`ProcessSandbox`,
never bare on the host:

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
does not isolate network egress, and ``RLIMIT_NPROC`` is deliberately not
used because it is per-UID and would break the host session. On Windows
the ``resource`` module is unavailable, so only the wall-time budget and
environment scrubbing are enforced; CPU/memory/file-size rlimits require a
POSIX host (the Docker images are Linux). Production containers (the Render
Docker service) add namespace isolation around this backend; a dedicated
container-per-run backend is the next step.
"""

from __future__ import annotations

import os
import shutil
import signal
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Sequence

from repomate_core.contracts import VerificationCheck, VerificationStatus
from repomate_core.repository.workspace import RepoWorkspace

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


class ProcessSandbox:
    def __init__(self, limits: SandboxLimits) -> None:
        self.limits = limits

    def run(self, argv: Sequence[str], cwd: Path) -> SandboxResult:
        env = {key: os.environ[key] for key in _ENV_ALLOWLIST if key in os.environ}
        env["PYTHONDONTWRITEBYTECODE"] = "1"
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
            process = subprocess.Popen([str(a) for a in argv], **popen_kwargs)
        except OSError as exc:
            return SandboxResult(None, "", f"failed to start: {exc}")

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
                None, _tail(stdout), _tail(stderr), timed_out=True, killed_reason=reason
            )
        return SandboxResult(process.returncode, _tail(stdout), _tail(stderr))


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


def sandbox_environment_description() -> str:
    """Human-readable, honest description of the active sandbox limits."""
    if _IS_POSIX:
        return "process sandbox (wall-time, CPU and memory limits, scrubbed env)"
    return (
        "process sandbox (wall-time kill, scrubbed env; "
        "CPU/memory limits unavailable on this OS)"
    )


def sandbox_limitations() -> list[str]:
    """Platform-specific limitations included in every receipt."""
    limitations = [
        "The process sandbox does not isolate network egress; a container-per-run "
        "backend is planned for untrusted-network toolchains.",
        "Repository tests run with RepoMate's interpreter and installed "
        "dependencies; a repo-specific virtualenv is not created, so missing "
        "dependencies can make the suite fail.",
    ]
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
    ws: RepoWorkspace, *, limits: Optional[SandboxLimits] = None
) -> VerificationCheck:
    """Execute the repository test suite inside the sandbox, or report an
    honest NOT_RUN when no supported toolchain exists."""
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

    sandbox = ProcessSandbox(limits or SandboxLimits())
    result = sandbox.run(command.argv, cwd=ws.root)
    combined = (result.stdout_tail + "\n" + result.stderr_tail).strip()

    if result.timed_out:
        return VerificationCheck(
            name="repository-test-suite",
            command=command.display,
            status=VerificationStatus.FAILED,
            reason=result.killed_reason,
            output_tail=combined,
        )
    status = VerificationStatus.PASSED if result.exit_code == 0 else VerificationStatus.FAILED
    return VerificationCheck(
        name="repository-test-suite",
        command=command.display,
        status=status,
        exit_code=result.exit_code,
        output_tail=combined,
    )
