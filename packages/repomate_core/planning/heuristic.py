"""Deterministic, offline planner.

Used when no model is configured, for tests, and as the classification
baseline. Every plan it produces is labelled ``heuristic-v1`` so reports
never misrepresent how they were made.

MVP scope: only DOCUMENTATION tasks proceed to artifact generation. Other
task types return ``need_more_info`` instead of forcing a change without
sufficient evidence — that is deliberate (PS04 sequencing), not a gap.
"""

from __future__ import annotations

import re
from typing import Optional

from repomate_core.contracts import (
    ContributionPlan,
    EvidenceRecord,
    PlannedChange,
    RepositorySnapshot,
    TaskType,
)
from repomate_core.planning.classify import (
    classify_task,
    default_acceptance_criteria,
)


def _pick_doc_target(
    snapshot: RepositorySnapshot, evidence: list[EvidenceRecord]
) -> Optional[str]:
    if snapshot.readme_path:
        return snapshot.readme_path
    for record in evidence:
        if record.kind.value in ("DOC", "SOURCE") and record.path.lower().endswith((".md", ".rst")):
            return record.path
    return None


def _summarize(task_text: str, limit: int = 140) -> str:
    text = re.sub(r"\s+", " ", task_text).strip()
    return (text[: limit - 1] + "…") if len(text) > limit else text


class HeuristicPlanner:
    name = "heuristic-v1"

    def plan(
        self,
        task_text: str,
        snapshot: RepositorySnapshot,
        evidence: list[EvidenceRecord],
    ) -> ContributionPlan:
        task_type = classify_task(task_text)
        evidence_ids = [record.id for record in evidence[:6]]
        limitations = [
            "Plan produced by the deterministic heuristic planner (no model provider configured).",
            "Scope and wording should be reviewed against the project's contributor guidelines.",
        ]
        if snapshot.license.status.value != "RECOGNIZED":
            limitations.append(
                f"License status is {snapshot.license.status.value}: {snapshot.license.note}"
            )

        if not evidence:
            return ContributionPlan(
                task_type=task_type,
                summary="No evidence could be located for this task.",
                acceptance_criteria=default_acceptance_criteria(),
                evidence_ids=[],
                limitations=limitations,
                need_more_info=True,
                questions=[
                    "No repository content matched the task; rephrase the task or confirm the repository."
                ],
                planned_by=self.name,
            )

        if task_type is not TaskType.DOCUMENTATION:
            return ContributionPlan(
                task_type=task_type,
                summary=(
                    f"Task classified as {task_type.value}; artifact generation for this "
                    "task type is not enabled in the MVP (documentation first)."
                ),
                acceptance_criteria=default_acceptance_criteria(),
                evidence_ids=evidence_ids,
                limitations=limitations,
                need_more_info=True,
                questions=[
                    "This task type is outside the MVP's supported scope; see docs/evaluation.md for the rollout order."
                ],
                planned_by=self.name,
            )

        target = _pick_doc_target(snapshot, evidence)
        if target is None:
            return ContributionPlan(
                task_type=task_type,
                summary="No documentation target (README or docs file) found.",
                acceptance_criteria=default_acceptance_criteria(),
                evidence_ids=evidence_ids,
                limitations=limitations,
                need_more_info=True,
                questions=["Which documentation file should receive this change?"],
                planned_by=self.name,
            )

        return ContributionPlan(
            task_type=TaskType.DOCUMENTATION,
            summary=f"Documentation change in {target}: {_summarize(task_text)}",
            planned_changes=[
                PlannedChange(
                    path=target,
                    change_type="MODIFY",
                    rationale="existing documentation file matching the task keywords",
                )
            ],
            acceptance_criteria=default_acceptance_criteria()
            + [f"New content cites the evidence it was derived from ({', '.join(evidence_ids[:3])})"],
            evidence_ids=evidence_ids,
            limitations=limitations,
            planned_by=self.name,
        )
