"""Bounded subprocess execution of git commands.

Every git invocation goes through :func:`run_git`: credentials prompts are
disabled, output is captured as UTF-8, wall-clock timeouts are enforced,
and an optional secret (e.g. a bearer token) is redacted from any error
message before it escapes this layer.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path
from typing import Optional

from repomate_core.repository.errors import WorkspaceError

GIT_TIMEOUT_SECONDS = 120


def run_git(
    *args: str,
    cwd: Path,
    timeout: int = GIT_TIMEOUT_SECONDS,
    check: bool = True,
    input_text: Optional[str] = None,
    redact: Optional[str] = None,
) -> subprocess.CompletedProcess:
    env = dict(os.environ)
    env["GIT_TERMINAL_PROMPT"] = "0"
    env.setdefault("GIT_TRACE", "0")
    cmd = ["git", "--no-pager", "-c", "core.autocrlf=false", *args]
    try:
        # Bytes mode is deliberate: ``text=True`` would translate "\n" to
        # os.linesep on Windows stdin, corrupting patches passed to
        # ``git apply -``. Decode the captured output ourselves instead.
        raw = subprocess.run(
            cmd,
            cwd=str(cwd),
            env=env,
            capture_output=True,
            timeout=timeout,
            input=input_text.encode("utf-8") if input_text is not None else None,
        )
    except subprocess.TimeoutExpired as exc:
        raise WorkspaceError(f"git command timed out after {timeout}s") from exc
    except OSError as exc:
        raise WorkspaceError(f"git command failed to start: {_redact(str(exc), redact)}") from exc
    result = subprocess.CompletedProcess(
        raw.args,
        raw.returncode,
        stdout=raw.stdout.decode("utf-8", errors="replace"),
        stderr=raw.stderr.decode("utf-8", errors="replace"),
    )
    if check and result.returncode != 0:
        stderr = _redact(result.stderr.strip(), redact)
        raise WorkspaceError(f"git {' '.join(args[:2])} failed: {stderr[:500]}")
    return result


def _redact(message: str, secret: Optional[str]) -> str:
    if secret and secret in message:
        return message.replace(secret, "***")
    return message
