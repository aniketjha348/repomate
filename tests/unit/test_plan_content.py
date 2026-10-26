"""Planner content parsing: model-written drafts and proposed edits."""

import json

from repomate_core.contracts import (
    EvidenceRecord,
    LicenseInfo,
    LicenseStatus,
    RepositorySnapshot,
)
from repomate_core.models import ModelResult
from repomate_core.planning.model_planner import ModelPlanner


class FakeProvider:
    name = "openai"
    model_id = "gemma4:31b"

    def __init__(self, payload: dict) -> None:
        self._payload = payload

    def complete(self, **kwargs) -> ModelResult:
        return ModelResult(
            text=json.dumps(self._payload), provider="openai", model="gemma4:31b"
        )


def _snapshot() -> RepositorySnapshot:
    return RepositorySnapshot(
        owner="a", name="b", url="u", default_branch="main", commit_sha="x" * 40,
        license=LicenseInfo(status=LicenseStatus.RECOGNIZED, spdx_id="MIT"),
        readme_path="README.md",
    )


def _evidence() -> list[EvidenceRecord]:
    return [EvidenceRecord(id="ev1", kind="DOC", path="README.md", rationale="r")]


def test_content_draft_parsed_and_fences_stripped():
    planner = ModelPlanner(FakeProvider({
        "task_type": "DOCUMENTATION",
        "summary": "document timeouts",
        "planned_changes": [{"path": "README.md"}],
        "content_draft": "```markdown\n## Timeouts\n\nSet `FOO_TIMEOUT`.\n```",
    }))
    plan = planner.plan("document timeouts", _snapshot(), _evidence())
    assert plan.content_draft is not None
    assert plan.content_draft.startswith("## Timeouts")
    assert "```" not in plan.content_draft
    assert plan.proposed_edits == []


def test_content_draft_fence_strip_preserves_leading_words():
    planner = ModelPlanner(FakeProvider({
        "task_type": "DOCUMENTATION",
        "summary": "explain markdown",
        "planned_changes": [{"path": "README.md"}],
        "content_draft": "```\nmarkdown is a markup language\n```",
    }))
    plan = planner.plan("explain markdown", _snapshot(), _evidence())
    # ``lstrip("markdown")`` used to eat the first word of the draft.
    assert plan.content_draft == "markdown is a markup language"


def test_proposed_edits_parsed_with_coercion():
    planner = ModelPlanner(FakeProvider({
        "task_type": "BUG_FIX",
        "summary": "guard against None",
        "planned_changes": [{"path": "src/core.py"}],
        "proposed_edits": [
            "just a string — invalid",
            {"path": "src/core.py", "old_text": "for item in items",
             "new_text": "for item in items or []", "rationale": "guard"},
            {"path": "src/core.py", "old_text": "x", "new_text": "  "},  # blank new_text
            {"old_text": "y", "new_text": "z"},  # no path
        ],
    }))
    plan = planner.plan("fix the crash", _snapshot(), _evidence())
    assert len(plan.proposed_edits) == 1
    edit = plan.proposed_edits[0]
    assert edit.old_text == "for item in items"
    assert edit.new_text == "for item in items or []"


def test_no_content_keys_becomes_need_more_info():
    planner = ModelPlanner(FakeProvider({
        "task_type": "DOCUMENTATION",
        "summary": "vague",
        "planned_changes": [{"path": "README.md"}],
    }))
    plan = planner.plan("document something", _snapshot(), _evidence())
    assert plan.need_more_info is True
    assert any("neither content_draft nor proposed_edits" in l for l in plan.limitations)
