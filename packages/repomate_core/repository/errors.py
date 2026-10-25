"""Repository-layer errors."""

from __future__ import annotations


class WorkspaceError(RuntimeError):
    """Controlled workspace/clone failure."""


class GitHubAccessError(RuntimeError):
    """Controlled GitHub access failure (not found, auth, network)."""


class RateLimitedError(GitHubAccessError):
    """GitHub API quota exhausted (typed, surfaced as RATE_LIMITED)."""

    def __init__(self, message: str, reset_at: float | None = None) -> None:
        super().__init__(message)
        self.reset_at = reset_at
