"""The pinned repository snapshot a run is bound to."""

from __future__ import annotations

from datetime import datetime
from typing import Literal, Optional

from pydantic import BaseModel, Field

from repomate_core.contracts._time import utcnow
from repomate_core.contracts.enums import LicenseStatus


class LicenseInfo(BaseModel):
    status: LicenseStatus
    spdx_id: Optional[str] = None
    file_path: Optional[str] = None
    note: str = ""


class EntryPoint(BaseModel):
    path: str
    kind: Literal["manifest", "script", "makefile", "readme"]
    detail: str = ""


class RepositorySnapshot(BaseModel):
    """Everything a run is pinned to. ``commit_sha`` is the exact commit
    the evidence was collected from and the patch is based on."""

    owner: str
    name: str
    url: str
    default_branch: str
    commit_sha: str
    license: LicenseInfo
    languages: dict[str, float] = {}
    file_count: int = 0
    readme_path: Optional[str] = None
    contributing_path: Optional[str] = None
    entry_points: list[EntryPoint] = []
    pinned_at: datetime = Field(default_factory=utcnow)
