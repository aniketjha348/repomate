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
from repomate_core.models.vyce import model_timeout_from_env

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
            max_output_tokens=4096,
            timeout=model_timeout_from_env(),
        )
        data = parse_model_json(raw.text)
        need_more_info = bool(data.get("need_more_info", False))
        changes = _coerce_changes(data.get("planned_changes") or [])
        if not changes and not need_more_info:
            raise ModelError(
                "model plan did not match the contract: no usable planned_changes "
                "(entries must be objects with at least a path)"
            )
        try:
            plan = ContributionPlan(
                task_type=TaskType(data.get("task_type", "UNKNOWN")),
                summary=str(data.get("summary", ""))[:1000],
                planned_changes=changes,
                acceptance_criteria=[str(c) for c in (data.get("acceptance_criteria") or [])[:8]],
                evidence_ids=[str(i) for i in (data.get("evidence_ids") or [])[:8]],
                limitations=[str(l) for l in (data.get("limitations") or [])[:8]],
                need_more_info=need_more_info,
                questions=[str(q) for q in (data.get("questions") or [])[:5]],
                planned_by=self.name,
            )
        except (ValueError, TypeError) as exc:
            raise ModelError(f"model plan did not match the contract: {exc}") from exc

        if not plan.summary:
            raise ModelError("model plan had an empty summary")
        return plan


def _coerce_changes(raw_entries: list) -> list[PlannedChange]:
    """Keep structurally valid entries; skip the rest.

    Some gateway models emit ``planned_changes`` as plain strings or
    partial objects (observed live with deepseek-v4-flash). Partial
    compliance is used rather than discarded, and zero usable entries is
    surfaced as a typed ModelError by the caller.
    """
    changes: list[PlannedChange] = []
    for entry in raw_entries:
        if not isinstance(entry, dict):
            continue
        path = entry.get("path")
        if not path or not isinstance(path, str):
            continue
        change_type = entry.get("change_type", "MODIFY")
        if change_type not in ("MODIFY", "CREATE"):
            change_type = "MODIFY"
        changes.append(
            PlannedChange(
                path=path,
                change_type=change_type,
                rationale=str(entry.get("rationale", ""))[:500],
            )
        )
    return changes[:5]


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
