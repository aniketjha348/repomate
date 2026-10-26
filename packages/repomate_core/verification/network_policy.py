"""Network egress policy for the verification sandbox.

Untrusted repository code and its test suite must not reach the network.
This module is the enforcement point, and it is deliberately **fail-closed**:

* the default mode is ``DISABLED`` (no egress at all);
* enforcement happens at the OS layer -- an unprivileged Linux namespace via
  ``bwrap`` (bubblewrap) with ``--unshare-net`` -- never through environment
  variables or Python-level checks, which untrusted code can simply ignore;
* if no enforcing backend exists on this host, the sandbox **refuses to run
  the command** rather than running it with network access. A test suite that
  cannot be isolated is reported ``NOT_RUN`` with the reason, which is the
  honest outcome. Silently running it with network access is not.

The policy is verified at runtime, not assumed: :func:`probe_egress_isolation`
executes real connection attempts inside the namespace before the repository
command is allowed to run. A receipt may only claim
``egress_validation: PASSED`` when that probe actually executed and passed.

The probe deliberately runs with ``python -I`` in a fresh, empty directory.
Running it from the repository would let a hostile ``sitecustomize.py`` or a
shadowing ``socket.py`` fake the verdict; the sandboxed code must never be
able to influence its own admission check.

Honest limitations (see docs/security.md):

* ``bwrap`` requires an unprivileged user namespace. Where the kernel or a
  container policy forbids it, no backend is available and the sandbox
  refuses to execute -- it does not fall back to an unisolated run.
* This module isolates the **network** and narrows the filesystem/process
  view. It is not a full VM: the repository under test is still writable,
  and the host kernel is shared.
* A network namespace blocks egress; it does not stop an already-downloaded
  dependency from running, and it does not make a repository's own code
  trustworthy.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Optional, Sequence

# Targets that must never be reachable from inside the sandbox. The probe
# checks each one for real; a single reachable target fails the boundary.
_PROBE_TARGETS = (
    ("public_http", "1.1.1.1", 80),
    ("cloud_metadata_ipv4", "169.254.169.254", 80),
    ("cloud_metadata_ipv6", "fd00:ec2::254", 80),
    ("private_rfc1918_10", "10.0.0.1", 80),
    ("private_rfc1918_172", "172.16.0.1", 80),
    ("private_rfc1918_192", "192.168.0.1", 80),
    ("loopback_postgres", "127.0.0.1", 5432),
    ("loopback_redis", "127.0.0.1", 6379),
    ("loopback_api", "127.0.0.1", 8000),
)
_PROBE_HOSTNAME = "example.com"
_PROBE_TIMEOUT_SECONDS = 45
_PROBE_MARKER = "REPOMATE_EGRESS_PROBE "
_PROBE_SCRIPT = f"""
import http.client, json, socket

targets = {_PROBE_TARGETS!r}
result = {{}}
for name, host, port in targets:
    try:
        sock = socket.create_connection((host, port), timeout=2)
        sock.close()
        result[name] = "reachable"
    except Exception as exc:
        result[name] = "blocked:" + type(exc).__name__
try:
    connection = http.client.HTTPSConnection({_PROBE_HOSTNAME!r}, 443, timeout=2)
    connection.connect()
    connection.close()
    result["public_https"] = "reachable"
except Exception as exc:
    result["public_https"] = "blocked:" + type(exc).__name__
try:
    socket.gethostbyname({_PROBE_HOSTNAME!r})
    result["dns"] = "resolved"
except Exception as exc:
    result["dns"] = "blocked:" + type(exc).__name__
print({_PROBE_MARKER!r} + json.dumps(result))
"""


# Read-only system trees a Python toolchain needs inside the sandbox. Anything
# not listed is simply absent, so the host's project tree and secret files are
# not visible.
_RO_SYSTEM_PATHS = ("/usr", "/bin", "/sbin", "/lib", "/lib64")

# ``/etc`` is deliberately NOT bound wholesale: it can contain credentials
# (git/apt auth files, cloud-init config, service environment files). Only
# the individual files needed by the dynamic loader, libc and Python are
# exposed.
_RO_ETC_PATHS = (
    "/etc/ld.so.cache",
    "/etc/ld.so.conf",
    "/etc/ld.so.conf.d",
    "/etc/passwd",
    "/etc/group",
    "/etc/nsswitch.conf",
    "/etc/host.conf",
    "/etc/hosts",
    "/etc/resolv.conf",
    "/etc/protocols",
    "/etc/services",
    "/etc/gai.conf",
    "/etc/ssl",
    "/etc/pki",
    "/etc/ca-certificates",
    "/etc/ca-certificates.conf",
    "/etc/localtime",
    "/etc/timezone",
    "/etc/mime.types",
    "/etc/fonts",
)

# Host directories that commonly hold control sockets: the container runtime
# (Docker/containerd/podman), supervisors, ssh-agent, X11. A network namespace
# does NOT cover unix domain sockets, so a broad filesystem bind leaves them
# reachable -- a real escape route. These are replaced with fresh empty tmpfs
# mounts. The repository bind is applied afterwards, so pytest's tmp_path
# still works when it lives below /tmp.
_MASKED_PATHS = ("/run", "/var/run", "/tmp", "/var/tmp", "/dev/shm")


class NetworkMode(str, Enum):
    """Requested egress policy for a sandboxed command."""

    DISABLED = "disabled"
    HOST = "host"


class EgressBackend(str, Enum):
    """Mechanism available on this host for enforcing the policy."""

    BWRAP = "bwrap"
    NONE = "none"


@dataclass(frozen=True)
class NetworkPolicy:
    """The effective policy plus whether it is actually enforceable."""

    mode: NetworkMode
    backend: EgressBackend

    @property
    def enforced(self) -> bool:
        """True only when egress is denied *and* a backend can enforce it."""
        return self.mode is NetworkMode.DISABLED and self.backend is not EgressBackend.NONE

    @property
    def blocks_egress(self) -> bool:
        return self.mode is NetworkMode.DISABLED

    def refusal_reason(self) -> str:
        """Why the command must not run, or an empty string if it may."""
        if self.mode is NetworkMode.HOST:
            return ""
        if self.backend is EgressBackend.NONE:
            return (
                "egress isolation is required but no enforcing backend is available "
                "on this host (needs bubblewrap/bwrap with unprivileged user "
                "namespaces); refusing to execute untrusted code with network access"
            )
        return ""


def detect_egress_backend() -> EgressBackend:
    """The strongest egress-enforcement mechanism this host offers.

    ``bwrap`` is the only backend. ``unshare --net`` alone was deliberately
    removed: it blocks IP egress but leaves the host filesystem (and therefore
    unix control sockets) visible, which is not enough to run untrusted code.
    """
    if os.name != "posix":
        return EgressBackend.NONE
    if shutil.which("bwrap"):
        return EgressBackend.BWRAP
    return EgressBackend.NONE


def resolve_network_policy(
    *, mode: Optional[NetworkMode] = None, backend: Optional[EgressBackend] = None
) -> NetworkPolicy:
    """Resolve the effective policy.

    ``mode`` defaults to the operator setting ``REPOMATE_SANDBOX_NETWORK``,
    and to ``DISABLED`` when unset. There is no model-facing or user-facing
    switch: a run cannot ask for network access, and an operator who enables
    it gets a receipt that says so. Any value other than the exact operator
    string ``host`` stays default-deny.
    """
    if mode is None:
        raw = os.environ.get("REPOMATE_SANDBOX_NETWORK", "").strip().lower()
        mode = NetworkMode.HOST if raw == "host" else NetworkMode.DISABLED
    return NetworkPolicy(mode=mode, backend=backend or detect_egress_backend())


def _interpreter_paths() -> list[str]:
    """Interpreter prefixes that must be visible for the toolchain to run.

    A virtualenv lives outside ``/usr``, so it is bound separately. The
    parent directories are created empty by the bind, which means the rest
    of the host project tree stays invisible.
    """
    paths: list[str] = []
    for attribute in ("prefix", "base_prefix"):
        value = getattr(sys, attribute, None)
        if value and value != "/" and value not in paths:
            paths.append(value)
    return paths


def _git_bind_args(root: Path) -> list[str]:
    """Keep the repository's git metadata intact but read-only.

    The workspace itself must be writable so the repository's tests can write
    fixtures. ``.git`` is different: a hostile test that edits
    ``.git/config`` could install a smudge/clean filter or ``core.fsmonitor``
    hook, and the host-side ``git reset --hard`` after verification would then
    execute it outside the sandbox. A read-only bind closes that escape; the
    host's post-run reset cannot be influenced by the sandboxed process.
    """
    git_dir = root / ".git"
    try:
        resolved = git_dir.resolve(strict=True)
    except OSError:
        # No git metadata exists, so there is nothing to make read-only.
        # Do not synthesize a mount point: the workspace's parent can be
        # read-only (for example /app in a container), and failing to create
        # it would make the whole sandbox refuse to start.
        return []
    if git_dir.is_symlink() or root not in resolved.parents:
        # A workspace should have a real .git directory. If it does not, mask
        # it rather than exposing an arbitrary host path.
        if git_dir.is_dir():
            return ["--tmpfs", str(git_dir)]
        return ["--ro-bind", "/dev/null", str(git_dir)]
    return ["--ro-bind", str(resolved), str(git_dir)]


def build_sandbox_argv(
    argv: Sequence[str],
    policy: NetworkPolicy,
    *,
    workspace: Optional[Path] = None,
) -> list[str]:
    """Wrap ``argv`` so it executes under the policy.

    Two isolation axes are applied together, because either one alone is
    escapable:

    * **network** -- an unprivileged network namespace (``--unshare-net``);
    * **filesystem/process** -- a minimal bind set and fresh pid/ipc/uts
      namespaces. Only read-only system paths, selected ``/etc`` files, the
      interpreter, and the repository under test are visible. The host's
      socket-bearing directories are replaced with empty tmpfs mounts, and
      the repository's ``.git`` directory is read-only.

    Returns the command to run. When the policy cannot be enforced the caller
    must not run it at all -- check :meth:`NetworkPolicy.refusal_reason` first.
    """
    command = [str(a) for a in argv]
    if policy.mode is NetworkMode.HOST:
        return command
    if policy.backend is EgressBackend.NONE:
        return command
    if policy.backend is not EgressBackend.BWRAP:  # pragma: no cover - enum guard
        return command

    args = [
        "bwrap",
        "--unshare-user-try",   # unprivileged user namespace when available
        "--unshare-net",        # no network interfaces except a down loopback
        # Without a PID namespace, a fresh procfs still enumerates every HOST
        # process. The sandbox gets its own process table and sees only itself.
        "--unshare-pid",
        "--unshare-ipc",        # no shared memory with host processes
        "--unshare-uts",        # private hostname/domainname
        "--unshare-cgroup-try",  # hide the host cgroup hierarchy if allowed
        "--die-with-parent",    # no orphaned processes if the parent dies
        "--new-session",        # detach from the controlling terminal
        "--hostname",
        "repomate-sandbox",
        "--cap-drop",
        "ALL",                  # no capabilities inside the sandbox
    ]
    # 1) Empty mounts where host control sockets live. These come first so a
    #    later bind of the workspace can still win where they overlap
    #    (pytest's tmp_path lives under /tmp).
    for path in _MASKED_PATHS:
        args += ["--tmpfs", path]
    # 2) Minimal read-only system.
    for path in _RO_SYSTEM_PATHS:
        args += ["--ro-bind-try", path, path]
    # 3) Selected /etc files only -- never credentials-bearing config trees.
    for path in _RO_ETC_PATHS:
        args += ["--ro-bind-try", path, path]
    # 4) The interpreter, which is not under /usr when it is a venv.
    for path in _interpreter_paths():
        if path not in _RO_SYSTEM_PATHS:
            args += ["--ro-bind-try", path, path]
    # 5) Synthesized /proc and /dev -- never the host's.
    args += ["--proc", "/proc", "--dev", "/dev"]
    # 6) The repository under test: the only writable host path.
    if workspace is not None:
        root = Path(workspace).resolve()
        args += ["--bind", str(root), str(root)]
        args += _git_bind_args(root)
        args += ["--chdir", str(root)]
    else:
        args += ["--chdir", "/"]
    args += ["--", *command]
    return args


def probe_egress_isolation(
    policy: NetworkPolicy, *, cwd: Optional[Path] = None
) -> tuple[bool, str]:
    """Actually attempt egress from inside the sandbox.

    The probe runs in a fresh empty directory with ``python -I`` so repository
    files cannot shadow ``socket``/``json`` or install a ``sitecustomize``
    module that fakes the result. ``cwd`` is accepted for API compatibility
    but is never used as the probe workspace.

    Returns ``(isolated, detail)``. ``isolated`` is True only when the probe
    ran and every target was refused. Any other outcome -- reachable, crashed,
    timed out -- is a failure, because the only safe answer is a proven block.
    """
    if policy.mode is NetworkMode.HOST:
        return False, "network mode is 'host': egress is permitted by configuration"
    if policy.backend is EgressBackend.NONE:
        return False, policy.refusal_reason() or "no egress backend"

    del cwd  # deliberately ignored: never let repository files influence the probe
    with tempfile.TemporaryDirectory(prefix="repomate-egress-probe-") as probe_dir:
        probe_path = Path(probe_dir)
        command = build_sandbox_argv(
            [sys.executable, "-I", "-c", _PROBE_SCRIPT],
            policy,
            workspace=probe_path,
        )
        env = {
            key: os.environ[key]
            for key in ("LANG", "LC_ALL")
            if key in os.environ
        }
        env["PATH"] = "/usr/local/bin:/usr/bin:/bin"
        env["HOME"] = "/tmp"
        env["TMPDIR"] = "/tmp"
        try:
            completed = subprocess.run(
                command,
                cwd=str(probe_path),
                env=env,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=_PROBE_TIMEOUT_SECONDS,
                check=False,
            )
        except (OSError, subprocess.SubprocessError) as exc:
            return False, f"egress probe could not execute: {type(exc).__name__}: {exc}"

    payload = _parse_probe_output(completed.stdout)
    if payload is None:
        detail = (completed.stderr or completed.stdout or "").strip()[:300]
        return False, f"egress probe produced no verdict (exit {completed.returncode}): {detail}"

    expected = {name for name, _, _ in _PROBE_TARGETS} | {"public_https", "dns"}
    missing = sorted(expected - set(payload))
    if missing:
        return False, f"egress probe did not test: {', '.join(missing)}"

    reachable = [
        name
        for name, state in payload.items()
        if not str(state).startswith("blocked")
    ]
    if reachable:
        return False, f"egress reached from inside the sandbox: {', '.join(sorted(reachable))}"
    return True, "every egress attempt was blocked (public, metadata, private, loopback, DNS)"


def _parse_probe_output(stdout: str) -> Optional[dict]:
    for line in stdout.splitlines():
        if line.startswith(_PROBE_MARKER):
            try:
                return json.loads(line[len(_PROBE_MARKER):])
            except json.JSONDecodeError:
                return None
    return None


def network_policy_record(
    policy: NetworkPolicy,
    *,
    egress_validation: str,
    egress_detail: str = "",
) -> dict:
    """The receipt's ``sandbox`` block.

    ``egress_validation`` is one of ``PASSED``, ``FAILED``, ``NOT_RUN`` or
    ``NOT_ENFORCED``, and must reflect what the probe actually did.
    ``policy_enforced`` is only true when the policy is deny-by-default, an
    enforcing backend exists, and the live probe passed.
    """
    return {
        "network_mode": policy.mode.value,
        "backend": policy.backend.value,
        "policy_enforced": policy.enforced and egress_validation == "PASSED",
        "egress_validation": egress_validation,
        "egress_detail": egress_detail,
    }
