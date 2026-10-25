"""Developer-supplied task input and the fetched GitHub issue."""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field, model_validator

from repomate_core.contracts._time import utcnow
from repomate_core.contracts.enums import TaskSource


class RepositoryInput(BaseModel):
    """Either a GitHub issue URL, or a repository URL plus a free-text
    development task.

    Shape only — URL/network policy is enforced by ``safety`` at the
    boundary so tests can construct inputs without policy coupling.
    """

    source: TaskSource
    issue_url: Optional[str] = None
    repo_url: Optional[str] = None
    task: Optional[str] = Field(default=None, max_length=4000)

    @model_validator(mode="after")
    def _check_source_fields(self) -> "RepositoryInput":
        if self.source is TaskSource.GITHUB_ISSUE and not self.issue_url:
            raise ValueError("issue_url is required for GITHUB_ISSUE input")
        if self.source is TaskSource.REPO_TASK:
            if not self.repo_url:
                raise ValueError("repo_url is required for REPO_TASK input")
            if not (self.task and self.task.strip()):
                raise ValueError("task is required for REPO_TASK input")
        return self


class GitHubIssue(BaseModel):
    url: str
    number: int
    title: str
    body: str = ""
    state: str = "open"
    labels: list[str] = []
    fetched_at: datetime = Field(default_factory=utcnow)
