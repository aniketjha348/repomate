"""Grounded planner backed by a model provider."""

from __future__ import annotations

import json
import os
from typing import Callable, Optional

from repomate_core.contracts import (
    ContributionPlan,
    EvidenceRecord,
    PlannedChange,
    ProposedClaim,
    ProposedEdit,
    RepositorySnapshot,
    TaskType,
)
from repomate_core.models import (
    ModelBudget,
    ModelError,
    ModelProvider,
    parse_model_json,
)
from repomate_core.models.openai import model_timeout_from_env

_SYSTEM_PROMPT = (
    "You are RepoMate's contribution planner. You plan a small, bounded "
    "open-source contribution grounded strictly in the provided evidence. "
    "Respond with ONLY a JSON object with keys: task_type (one of "
    "DOCUMENTATION|BUG_FIX|TEST|FEATURE|REFACTOR|UNKNOWN), summary (string), "
    "planned_changes (array of {path, change_type: MODIFY|CREATE, rationale}), "
    "acceptance_criteria (array of strings), evidence_ids (array of the "
    "evidence ids you relied on), limitations (array of strings), "
    "need_more_info (boolean), questions (array of strings), plus exactly one "
    "of the content keys: "
    "content_draft — for DOCUMENTATION tasks: the actual markdown section to "
    "append (5-20 lines, grounded in the evidence, no code fences around the "
    "whole section); "
    "or proposed_edits — for BUG_FIX/TEST/FEATURE/REFACTOR tasks: an array of "
    "{path, old_text, new_text, rationale} where old_text is copied VERBATIM "
    "from the pinned snapshot (quote it from the evidence snippets, 1-8 "
    "contiguous lines) and new_text is the minimal replacement; empty old_text "
    "creates a new file. "
    "Also include proposed_claims: an array of {text, evidence_ids} — one entry "
    "per assertion your plan depends on, each citing the specific evidence ids "
    "that support THAT assertion. Every evidence id you cite is checked against "
    "this run's evidence set; a citation that does not exist, or that shares no "
    "vocabulary with its claim, is recorded as an unsupported hypothesis. "
    "If the evidence is insufficient to act, set need_more_info=true and "
    "list precise questions. Never invent file paths that are not in the "
    "evidence or repository snapshot."
)


class ModelPlanner:
    def __init__(
        self,
        provider: ModelProvider,
        *,
        budget: Optional[ModelBudget] = None,
        guard: Optional[Callable[[], None]] = None,
        remaining_seconds: Optional[Callable[[], float]] = None,
    ) -> None:
        self._provider = provider
        self._budget = budget
        self._guard = guard
        self._remaining_seconds = remaining_seconds

    @property
    def name(self) -> str:
        provider = self._provider
        return f"model:{provider.name}/{getattr(provider, 'model_id', '?')}"

    @property
    def provider(self) -> ModelProvider:
        return self._provider

    def bind_runtime(
        self,
        *,
        budget: ModelBudget,
        guard: Callable[[], None],
        remaining_seconds: Callable[[], float],
    ) -> None:
        """Attach the run's budget and cancellation guard to this planner.

        The same budget is shared with the tool loop, so research calls and
        the planning call are charged to one per-run cap rather than each
        getting a fresh allowance.
        """
        self._budget = budget
        self._guard = guard
        self._remaining_seconds = remaining_seconds

    def _timeout(self) -> float:
        timeout = model_timeout_from_env()
        if self._remaining_seconds is not None:
            timeout = max(0.5, min(timeout, self._remaining_seconds()))
        return timeout

    def _complete(self, user_json: str, *, correction: str | None):
        if self._guard is not None:
            self._guard()
        system = _SYSTEM_PROMPT
        if correction is not None:
            system += (
                "\nYour previous response was NOT valid JSON (it began: "
                f"{correction!r}). Return ONLY a syntactically valid JSON "
                "object — escape newlines inside strings as \\n and quotes "
                "as \\\". No markdown fences, no prose."
            )
        estimated_prompt = max(1, (len(system) + len(user_json)) // 4)
        if self._budget is not None:
            self._budget.start_call(estimated_prompt_tokens=estimated_prompt)
        result = self._provider.complete(
            system=system,
            user=user_json,
            max_output_tokens=4096,
            timeout=self._timeout(),
            json_mode=True,
        )
        if self._budget is not None:
            self._budget.record_result(
                result, estimated_prompt_tokens=estimated_prompt
            )
        if self._guard is not None:
            self._guard()
        return result

    def plan(
        self,
        task_text: str,
        snapshot: RepositorySnapshot,
        evidence: list[EvidenceRecord],
    ) -> ContributionPlan:
        raw = self._complete(user_payload(task_text, snapshot, evidence), correction=None)
        try:
            data = parse_model_json(raw.text)
        except ModelError:
            # One bounded corrective retry: tell the model its previous
            # output was invalid JSON and ask for strict JSON only.
            raw = self._complete(
                user_payload(task_text, snapshot, evidence),
                correction=raw.text[:1000],
            )
            data = parse_model_json(raw.text)
        need_more_info = bool(data.get("need_more_info", False))
        changes = _coerce_changes(data.get("planned_changes") or [])
        edits = _coerce_edits(data.get("proposed_edits") or [])
        content_draft = _clean_draft(data.get("content_draft"))
        claims = _coerce_claims(data.get("proposed_claims") or [])
        has_content = bool(edits or content_draft)
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
                proposed_claims=claims,
                content_draft=content_draft,
                proposed_edits=edits,
                # Preserved verbatim so the model's original output stays
                # auditable next to the validator's verdict.
                raw_response=raw.text[:20000],
            )
        except (ValueError, TypeError) as exc:
            raise ModelError(f"model plan did not match the contract: {exc}") from exc

        if not plan.summary:
            raise ModelError("model plan had an empty summary")
        if not need_more_info and not has_content:
            # A plan that neither drafts content nor proposes edits cannot
            # produce an artifact — surface that honestly instead of
            # letting generation fail opaquely.
            plan.limitations.append(
                "model returned neither content_draft nor proposed_edits"
            )
            plan.need_more_info = True
        return plan


def _coerce_changes(raw_entries: list) -> list[PlannedChange]:
    """Keep structurally valid entries; skip the rest.

    Some gateway models emit ``planned_changes`` as plain strings or
    partial objects (observed live with some gateway models). Partial
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


def _coerce_edits(raw_entries: list) -> list[ProposedEdit]:
    """Valid search/replace edits only: verbatim old_text (or empty for a
    new file), non-empty new_text, path present."""
    edits: list[ProposedEdit] = []
    for entry in raw_entries:
        if not isinstance(entry, dict):
            continue
        path = entry.get("path")
        old_text = entry.get("old_text")
        new_text = entry.get("new_text")
        if not path or not isinstance(path, str):
            continue
        if not isinstance(old_text, str) or not isinstance(new_text, str):
            continue
        if not new_text.strip():
            continue
        edits.append(
            ProposedEdit(
                path=path,
                old_text=old_text[:8000],
                new_text=new_text[:8000],
                rationale=str(entry.get("rationale", ""))[:500],
            )
        )
    return edits[:5]


def _coerce_claims(raw_entries: list) -> list[ProposedClaim]:
    """Keep structurally valid claims; skip the rest.

    A claim without text carries no assertion and is dropped. A claim with
    no citations is kept: the validator records it as a hypothesis, which
    is more honest than silently discarding the model's assertion.
    """
    claims: list[ProposedClaim] = []
    for entry in raw_entries:
        if not isinstance(entry, dict):
            continue
        text = entry.get("text")
        if not isinstance(text, str) or not text.strip():
            continue
        raw_ids = entry.get("evidence_ids") or []
        if not isinstance(raw_ids, list):
            raw_ids = []
        claims.append(
            ProposedClaim(
                text=text.strip()[:1000],
                evidence_ids=[str(i) for i in raw_ids[:8]],
            )
        )
    return claims[:12]


def _clean_draft(raw) -> str | None:
    """Bounded, fence-free markdown section from the model."""
    if not isinstance(raw, str) or not raw.strip():
        return None
    draft = raw.strip()
    if draft.startswith("```"):
        # Drop the opening fence line (``` or ```markdown) and the closing
        # fence. Do not character-strip: ``lstrip("markdown")`` used to eat
        # real leading words such as "markdown is a markup language".
        lines = draft.splitlines()[1:]
        while lines and not lines[-1].strip():
            lines.pop()
        if lines and lines[-1].strip().startswith("```"):
            lines.pop()
        draft = "\n".join(lines).strip()
    return draft[:8000] or None


def user_payload(task_text: str, snapshot: RepositorySnapshot, evidence: list[EvidenceRecord]) -> str:
    return json.dumps(_build_context(task_text, snapshot, evidence), indent=2)


def _snippet_chars() -> int:
    """Per-evidence snippet budget for the planner prompt.

    The prompt is the latency driver: a gateway sitting behind a ~100s edge
    timeout (Cloudflare 524) gives up on oversized reasoning prompts. 600
    characters per record keeps the grounding intact while cutting the
    payload enough to stay inside that window; tune with
    ``REPOMATE_PLANNER_SNIPPET_CHARS``.
    """
    raw = os.environ.get("REPOMATE_PLANNER_SNIPPET_CHARS", "").strip()
    try:
        return max(200, min(int(raw), 4000)) if raw else 600
    except ValueError:
        return 600


def _max_evidence_records() -> int:
    raw = os.environ.get("REPOMATE_PLANNER_MAX_EVIDENCE", "").strip()
    try:
        return max(1, min(int(raw), 12)) if raw else 6
    except ValueError:
        return 6


def _build_context(
    task_text: str,
    snapshot: RepositorySnapshot,
    evidence: list[EvidenceRecord],
) -> dict:
    snippet_chars = _snippet_chars()
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
                "snippet": r.snippet[:snippet_chars],
            }
            for r in evidence[:_max_evidence_records()]
        ],
    }
