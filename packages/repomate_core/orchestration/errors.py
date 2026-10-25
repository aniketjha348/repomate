"""Controlled pipeline failures and cooperative cancellation."""

from __future__ import annotations

from repomate_core.contracts import ErrorCode, RunError


class PipelineError(Exception):
    """A controlled, typed pipeline failure."""

    def __init__(self, code: ErrorCode, message: str, detail: str = "") -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.detail = detail

    def to_run_error(self) -> RunError:
        return RunError(code=self.code, message=self.message, detail=self.detail)


class RunCancelled(Exception):
    """Raised between stages when a cancellation marker is present."""
