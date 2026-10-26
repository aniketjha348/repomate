"""Request/response models for the API routes."""

from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, ConfigDict, Field

from repomate_core.contracts import RunStatus


class CreateRunRequest(BaseModel):
    # A run may not ask for network access or override sandbox policy. Unknown
    # fields are rejected rather than silently ignored, so a caller trying
    # ``{"network": "host"}`` gets a 422 instead of a false sense that it took
    # effect.
    model_config = ConfigDict(extra="forbid")

    issue_url: Optional[str] = Field(default=None, max_length=2000)
    repo_url: Optional[str] = Field(default=None, max_length=2000)
    task: Optional[str] = Field(default=None, max_length=4000)


class RunCreatedResponse(BaseModel):
    run_id: str
    status: RunStatus
    links: dict[str, str]


class RunSummary(BaseModel):
    run_id: str
    status: RunStatus
    created_at: str
    planner: str


class CancelledResponse(BaseModel):
    run_id: str
    cancelled: bool
