"""The contribution plan produced by a planner."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel

from repomate_core.contracts.enums import TaskType


class PlannedChange(BaseModel):
    path: str
    change_type: Literal["MODIFY", "CREATE"]
    rationale: str


class ContributionPlan(BaseModel):
    task_type: TaskType
    summary: str
    planned_changes: list[PlannedChange] = []
    acceptance_criteria: list[str] = []
    evidence_ids: list[str] = []
    limitations: list[str] = []
    need_more_info: bool = False
    questions: list[str] = []
    planned_by: str = ""
