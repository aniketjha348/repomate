"""API settings, sourced from the environment."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

DEFAULT_ORIGINS = ("http://localhost:3000", "http://127.0.0.1:3000")

SSE_POLL_SECONDS = 0.8
SSE_MAX_SECONDS = 900.0


def _cors_origins_from_env() -> list[str]:
    origins = list(DEFAULT_ORIGINS)
    raw = os.environ.get("ALLOWED_ORIGINS", "")
    for entry in raw.split(","):
        entry = entry.strip()
        if entry and entry not in origins:
            origins.append(entry)
    return origins


def _env_positive_int(name: str, default: int) -> int:
    try:
        value = int(os.environ.get(name, str(default)))
    except ValueError:
        return default
    return value if value > 0 else default


def _env_positive_float(name: str, default: float) -> float:
    try:
        value = float(os.environ.get(name, str(default)))
    except ValueError:
        return default
    return value if value > 0 else default


def _trusted_proxies_from_env() -> list[str]:
    """IPs/CIDRs whose ``X-Forwarded-For`` header is believed.

    Empty by default: without an explicitly configured trusted proxy the
    socket peer address is the client identity, so a caller cannot spoof its
    way around the per-IP rate limit with a header.
    """
    raw = os.environ.get("REPOMATE_TRUSTED_PROXIES", "")
    return [entry.strip() for entry in raw.split(",") if entry.strip()]


@dataclass
class Settings:
    runs_root: Path = field(
        default_factory=lambda: Path(os.environ.get("REPOMATE_RUNS_ROOT", "var/runs"))
    )
    database_url: str | None = field(
        default_factory=lambda: os.environ.get("REPOMATE_DATABASE_URL") or None
    )
    github_token: str | None = field(
        default_factory=lambda: os.environ.get("GITHUB_TOKEN") or None
    )
    keep_workspace: bool = field(
        default_factory=lambda: os.environ.get("REPOMATE_KEEP_WORKSPACE", "0") == "1"
    )
    max_run_seconds: float = field(
        default_factory=lambda: float(os.environ.get("REPOMATE_MAX_RUN_SECONDS", "900"))
    )
    sandbox_enabled: bool = field(
        default_factory=lambda: os.environ.get("REPOMATE_SANDBOX_ENABLED", "1") == "1"
    )
    execution: str = field(
        default_factory=lambda: os.environ.get("REPOMATE_EXECUTION", "inproc")
    )
    redis_url: str = field(
        default_factory=lambda: os.environ.get("REDIS_URL", "redis://localhost:6379/0")
    )
    cors_origins: list[str] = field(default_factory=_cors_origins_from_env)
    # Fair-use admission (docs/security.md). The rate limit is a per-client
    # sliding window; the concurrent-run cap protects the worker pool and the
    # model budget. Both are configurable and fail closed.
    rate_limit_requests: int = field(
        default_factory=lambda: _env_positive_int("REPOMATE_RATE_LIMIT_REQUESTS", 20)
    )
    rate_limit_window_seconds: float = field(
        default_factory=lambda: _env_positive_float(
            "REPOMATE_RATE_LIMIT_WINDOW_SECONDS", 60.0
        )
    )
    max_concurrent_runs: int = field(
        default_factory=lambda: _env_positive_int("REPOMATE_MAX_CONCURRENT_RUNS", 3)
    )
    trusted_proxies: list[str] = field(default_factory=_trusted_proxies_from_env)


def read_settings() -> Settings:
    """Fresh snapshot per request path (env can change in tests)."""
    return Settings()
