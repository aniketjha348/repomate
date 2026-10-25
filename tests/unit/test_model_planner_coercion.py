"""ModelPlanner robustness: models with partial schema compliance.

Real-world finding (docs/model-matrix.md): deepseek-v4-flash returns
``planned_changes`` as an array of plain strings. The planner must use
whatever valid object entries exist, and fail honestly (ModelError) when
the model produces none at all.
"""

import pytest

from repomate_core.contracts import (
    ContributionPlan,
    EvidenceRecord,
    LicenseInfo,
    LicenseStatus,
    RepositorySnapshot,
    TaskType,
)
from repomate_core.models import ModelError, ModelResult
from repomate_core.planning.model_planner import ModelPlanner


class FakeProvider:
    name = "fake"
    model_id = "fake-1"

    def __init__(self, payload: dict) -> None:
        self._payload = payload

    def complete(self, **kwargs) -> ModelResult:
        import json

        return ModelResult(text=json.dumps(self._payload), provider="fake", model="fake-1")


def _snapshot() -> RepositorySnapshot:
    return RepositorySnapshot(
        owner="a", name="b", url="u", default_branch="main", commit_sha="x" * 40,
        license=LicenseInfo(status=LicenseStatus.RECOGNIZED, spdx_id="MIT"),
        readme_path="README.md",
    )


def _evidence() -> list[EvidenceRecord]:
    return [EvidenceRecord(id="ev1", kind="DOC", path="README.md", rationale="r")]


def _plan_with(changes) -> dict:
    return {
        "task_type": "DOCUMENTATION",
        "summary": "document the thing",
        "planned_changes": changes,
        "need_more_info": False,
    }


def test_mixed_changes_only_objects_survive():
    planner = ModelPlanner(FakeProvider(_plan_with([
        "Locate the Usage section",
        {"path": "README.md", "rationale": "docs target"},
        {"path": "docs/x.md", "change_type": "CREATE"},
        {"no_path": True},
    ])))
    plan = planner.plan("document it", _snapshot(), _evidence())
    assert [c.path for c in plan.planned_changes] == ["README.md", "docs/x.md"]
    assert plan.planned_changes[0].change_type == "MODIFY"  # defaulted
    assert plan.planned_changes[1].change_type == "CREATE"


def test_invalid_change_type_coerced():
    planner = ModelPlanner(FakeProvider(_plan_with([
        {"path": "README.md", "change_type": "DELETE EVERYTHING"},
    ])))
    plan = planner.plan("document it", _snapshot(), _evidence())
    assert plan.planned_changes[0].change_type == "MODIFY"


def test_all_string_changes_raises_model_error():
    planner = ModelPlanner(FakeProvider(_plan_with([
        "Locate the Usage section", "Add examples",
    ])))
    with pytest.raises(ModelError, match="no usable planned_changes"):
        planner.plan("document it", _snapshot(), _evidence())


def test_need_more_info_plan_needs_no_changes():
    planner = ModelPlanner(FakeProvider({
        "task_type": "DOCUMENTATION", "summary": "insufficient",
        "planned_changes": ["just strings"], "need_more_info": True,
    }))
    plan = planner.plan("document it", _snapshot(), _evidence())
    assert plan.need_more_info is True
    assert isinstance(plan, ContributionPlan)
