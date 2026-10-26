"""Optional ``.env`` loading for RepoMate's process entry points.

RepoMate reads *all* configuration from the environment, and the README
tells operators to copy ``.env.example`` to ``.env``. Something has to
actually read that file, so the entry points (HTTP API, Celery worker,
the developer harnesses) call :func:`load_env_file` once at startup,
before any settings are read.

Two rules keep this honest and safe:

- **The real environment always wins.** A variable already present in
  ``os.environ`` is never overwritten, so container, CI and shell
  configuration cannot be silently replaced by a stray file. (An empty
  value counts as present — that is how the test suite pins the
  heuristic planner.)
- **Tests can opt out.** ``REPOMATE_SKIP_DOTENV=1`` disables loading
  entirely, which is what the hermetic suite sets so a developer's local
  ``.env`` can never change a test outcome.

Deliberately stdlib-only: RepoMate's runtime dependencies stay
``pydantic`` + ``httpx``.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Iterator, Optional

SKIP_ENV_VAR = "REPOMATE_SKIP_DOTENV"
ENV_FILE_VAR = "REPOMATE_ENV_FILE"

_loaded_path: Optional[Path] = None


def _default_env_path() -> Path:
    """``.env`` in the working directory, else at the repository root."""
    candidates = [
        Path.cwd() / ".env",
        Path(__file__).resolve().parents[2] / ".env",
    ]
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    return candidates[0]


def _parse(text: str) -> Iterator[tuple[str, str]]:
    """Yield ``(key, value)`` pairs from dotenv-style text.

    Tolerates blank lines, ``#`` comments, an ``export`` prefix, and
    single- or double-quoted values. Malformed lines are skipped rather
    than raising: a broken ``.env`` must not stop the service booting.
    """
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[len("export ") :].lstrip()
        key, sep, value = line.partition("=")
        if not sep:
            continue
        key = key.strip()
        if not key:
            continue
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        yield key, value


def load_env_file(
    path: Optional[Path | str] = None, *, override: bool = False
) -> Optional[Path]:
    """Load ``.env`` into ``os.environ``.

    Returns the path that was read, or ``None`` when loading was skipped
    (opt-out set) or no file exists. Existing variables are preserved
    unless ``override`` is passed.
    """
    global _loaded_path
    if os.environ.get(SKIP_ENV_VAR, "").strip() == "1":
        return None

    target = Path(path) if path is not None else Path(
        os.environ.get(ENV_FILE_VAR) or _default_env_path()
    )
    if not target.is_file():
        return None
    try:
        text = target.read_text(encoding="utf-8")
    except OSError:
        return None

    for key, value in _parse(text):
        if override or key not in os.environ:
            os.environ[key] = value
    _loaded_path = target
    return target


def loaded_env_file() -> Optional[str]:
    """The ``.env`` this process loaded, if any — surfaced by ``/api/health``
    so "why is my planner heuristic?" has a visible answer."""
    return str(_loaded_path) if _loaded_path is not None else None
