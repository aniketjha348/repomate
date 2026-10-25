"""Unit tests for the heuristic planner and task classification."""

from repomate_core.contracts import (
    EvidenceKind,
    EvidenceRecord,
    LicenseInfo,
    LicenseStatus,
    RepositorySnapshot,
    TaskType,
)
from repomate_core.planning.planner import HeuristicPlanner, classify_task


def _snapshot(**overrides) -> RepositorySnapshot:
    defaults = dict(
        owner="acme",
        name="fixture-project",
        url="https://github.com/acme/fixture-project",
        default_branch="main",
        commit_sha="a" * 40,
        license=LicenseInfo(status=LicenseStatus.RECOGNIZED, spdx_id="MIT", file_path="LICENSE"),
        languages={"py": 100.0},
        file_count=6,
        readme_path="README.md",
    )
    defaults.update(overrides)
    return RepositorySnapshot(**defaults)


def _evidence(*paths: str) -> list[EvidenceRecord]:
    return [
        EvidenceRecord(
            id=f"ev{i}",
            kind=EvidenceKind.DOC,
            path=path,
            start_line=1,
            end_line=3,
            snippet="# content",
            rationale="matches keywords",
        )
        for i, path in enumerate(paths, start=1)
    ]


class TestClassify:
    def test_docs(self):
        assert classify_task("Add documentation for the timeout option") is TaskType.DOCUMENTATION

    def test_bug(self):
        assert classify_task("fix the crash in the parser") is TaskType.BUG_FIX

    def test_test(self):
        assert classify_task("add a regression test for timeouts") is TaskType.TEST

    def test_unknown(self):
        assert classify_task("make it better somehow") is TaskType.UNKNOWN


class TestHeuristicPlanner:
    def test_documentation_plan_targets_readme(self):
        plan = HeuristicPlanner().plan(
            "Add documentation for the timeout option to the README",
            _snapshot(),
            _evidence("README.md", "docs/usage.md"),
        )
        assert plan.task_type is TaskType.DOCUMENTATION
        assert plan.planned_changes[0].path == "README.md"
        assert plan.planned_changes[0].change_type == "MODIFY"
        assert plan.planned_by == "heuristic-v1"
        assert not plan.need_more_info
        assert plan.acceptance_criteria

    def test_no_evidence_forces_need_more_info(self):
        plan = HeuristicPlanner().plan("document the flange", _snapshot(), [])
        assert plan.need_more_info
        assert plan.questions

    def test_non_documentation_task_deferred(self):
        plan = HeuristicPlanner().plan(
            "fix the crash in the parser", _snapshot(), _evidence("src/core.py")
        )
        assert plan.need_more_info
        assert plan.task_type is TaskType.BUG_FIX

    def test_unlicensed_repo_recorded_as_limitation(self):
        snapshot = _snapshot(license=LicenseInfo(status=LicenseStatus.ABSENT))
        plan = HeuristicPlanner().plan(
            "Add documentation for the timeout option", snapshot, _evidence("README.md")
        )
        assert any("License status is ABSENT" in l for l in plan.limitations)
