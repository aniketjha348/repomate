"""The contribution plan produced by a planner."""

from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel, Field

from repomate_core.contracts.enums import TaskType


class PlannedChange(BaseModel):
    path: str
    change_type: Literal["MODIFY", "CREATE"]
    rationale: str


class ProposedClaim(BaseModel):
    """An assertion the model wants to make, with the evidence it cites.

    Optional in the model contract: a model that supplies claims gets
    claim-level grounding; one that does not has its plan's own assertions
    (summary, acceptance criteria) bound to the flat ``evidence_ids`` list
    instead. Either way the validator assigns ``support_status``.
    """

    text: str = Field(min_length=1, max_length=1000)
    evidence_ids: list[str] = []


class ProposedEdit(BaseModel):
    """A model-proposed search/replace edit, anchored to exact text.

    ``old_text`` must be quoted verbatim from the pinned snapshot (the
    evidence snippets); ``new_text`` is the replacement. Empty
    ``old_text`` means "create this file".
    """

    path: str
    old_text: str = Field(min_length=0, max_length=8000)
    new_text: str = Field(min_length=0, max_length=8000)
    rationale: str = ""


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
    # Claims the model chose to bind to specific evidence. Empty means the
    # plan's own assertions are validated against ``evidence_ids`` instead.
    proposed_claims: list[ProposedClaim] = []
    # The model's original response, preserved verbatim so the raw output
    # stays auditable alongside the validator's verdict.
    raw_response: str = ""
    # Model-backed planners may carry the actual artifact content:
    content_draft: Optional[str] = Field(default=None, max_length=8000)
    proposed_edits: list[ProposedEdit] = []
