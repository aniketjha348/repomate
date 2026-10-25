"""Grounded planner backed by a model provider."""

from __future__ import annotations

import json

from repomate_core.contracts import (
    ContributionPlan,
    EvidenceRecord,
    PlannedChange,
    RepositorySnapshot,
    TaskType,
)
from repomate_core.models import ModelError, ModelProvider, parse_model_json

_SYSTEM_PROMPT = (
    "You are RepoMate's contribution planner. You plan a small, bounded "
    "open-source contribution grounded strictly in the provided evidence. "
    "Respond with ONLY a JSON object with keys: task_type (one of "
    "DOCUMENTATION|BUG_FIX|TEST|FEATURE|REFACTOR|UNKNOWN), summary (string), "
    "planned_changes (array of {path, change_type: MODIFY|CREATE, rationale}), "
    "acceptance_criteria (array of strings), evidence_ids (array of the "
    "evidence ids you relied on), limitations (array of strings), "
    "need_more_info (boolean), questions (array of strings). "
    "If the evidence is insufficient to act, set need_more_info=true and "
    "list precise questions. Never invent file paths that are not in the "
    "evidence or repository snapshot."
)


class ModelPlanner:
    def __init__(self, provider: ModelProvider) -> None:
        self._provider = provider
        self.name = f"model:{provider.name}/{getattr(provider, 'model_id', '?')}"

    def plan(
        self,
        task_text: str,
        snapshot: RepositorySnapshot,
        evidence: list[EvidenceRecord],
    ) -> ContributionPlan:
        raw = self._provider.complete(
            system=_SYSTEM_PROMPT,
            user=json.dumps(_build_context(task_text, snapshot, evidence), indent=2),
            max_output_tokens=2048,
        )
        data = parse_model_json(raw.text)
        try:
            plan = ContributionPlan(
                task_type=TaskType(data.get("task_type", "UNKNOWN")),
                summary=str(data.get("summary", ""))[:1000],
                planned_changes=[
                    PlannedChange(**change)
                    for change in (data.get("planned_changes") or [])[:5]
                ],
                acceptance_criteria=[str(c) for c in (data.get("acceptance_criteria") or [])[:8]],
                evidence_ids=[str(i) for i in (data.get("evidence_ids") or [])[:8]],
                limitations=[str(l) for l in (data.get("limitations") or [])[:8]],
                need_more_info=bool(data.get("need_more_info", False)),
                questions=[str(q) for q in (data.get("questions") or [])[:5]],
                planned_by=self.name,
            )
        except (ValueError, TypeError) as exc:
            raise ModelError(f"model plan did not match the contract: {exc}") from exc

        if not plan.summary:
            raise ModelError("model plan had an empty summary")
        return plan


def _build_context(
    task_text: str,
    snapshot: RepositorySnapshot,
    evidence: list[EvidenceRecord],
) -> dict:
    return {
        "task": task_text,
        "repository": {
            "slug": f"{snapshot.owner}/{snapshot.name}",
            "commit": snapshot.commit_sha,
            "license": snapshot.license.model_dump(),
            "readme": snapshot.readme_path,
            "entry_points": [e.model_dump() for e in snapshot.entry_points[:5]],
        },
        "evidence": [
            {
                "id": r.id,
                "path": r.path,
                "lines": [r.start_line, r.end_line],
                "snippet": r.snippet[:1000],
            }
            for r in evidence[:8]
        ],
    }
