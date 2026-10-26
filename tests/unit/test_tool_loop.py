"""Bounded model tool loop: typed tools, evidence validation, hard limits."""

import json

import pytest

from repomate_core.contracts import (
    EvidenceKind,
    ModelBudgetLimits,
    RepositorySnapshot,
    ToolLoopLimits,
    ToolLoopStatus,
    ToolName,
)
from repomate_core.evidence.tools import run_tool_loop
from repomate_core.evidence.validation import (
    normalize_evidence_path,
    validate_retrieved_evidence,
)
from repomate_core.models import ModelBudget, ModelBudgetExceeded, ModelResult
from repomate_core.repository.inspect import inspect_repository
from repomate_core.repository.workspace import RepoWorkspace


class ScriptedProvider:
    name = "fake"
    model_id = "fake-1"

    def __init__(self, responses: list[object]) -> None:
        self._responses = list(responses)
        self.calls = 0

    def complete(self, **kwargs) -> ModelResult:
        self.calls += 1
        response = self._responses.pop(0)
        text = response if isinstance(response, str) else json.dumps(response)
        return ModelResult(
            text=text,
            provider="fake",
            model="fake-1",
            usage={"prompt_tokens": 10, "completion_tokens": 5},
        )


@pytest.fixture
def snapshot(local_workspace: RepoWorkspace) -> RepositorySnapshot:
    return inspect_repository(
        local_workspace,
        owner="acme",
        name="fixture-project",
        url="https://github.com/acme/fixture-project",
    )


def _run(
    workspace: RepoWorkspace,
    snapshot: RepositorySnapshot,
    provider: ScriptedProvider,
    limits: ToolLoopLimits | None = None,
    budget: ModelBudget | None = None,
):
    return run_tool_loop(
        workspace,
        snapshot,
        "Add documentation for the timeout option",
        provider,
        [],
        limits or ToolLoopLimits(),
        budget=budget,
    )


def test_read_file_returns_validated_evidence(
    local_workspace, snapshot
):
    provider = ScriptedProvider(
        [
            {
                "tool": "read_file",
                "path": "src/fixture/core.py",
                "start_line": 1,
                "end_line": 4,
            },
            {"tool": "done"},
        ]
    )
    outcome = _run(local_workspace, snapshot, provider)

    assert outcome.report.status is ToolLoopStatus.COMPLETE
    assert outcome.report.model_calls == 2
    assert outcome.report.tool_calls == 1
    assert outcome.report.records_added == 1
    assert outcome.report.rejected_items == 0
    assert len(outcome.records) == 1
    record = outcome.records[0]
    assert record.path == "src/fixture/core.py"
    assert record.start_line == 1 and record.end_line == 4
    assert record.snippet.startswith('"""Core processing helpers."""')
    assert outcome.report.calls[0].tool is ToolName.READ_FILE
    assert outcome.report.calls[0].evidence_paths == ["src/fixture/core.py"]


def test_search_text_returns_only_real_file_ranges(local_workspace, snapshot):
    provider = ScriptedProvider(
        [
            {"tool": "search_text", "query": "timeout", "max_results": 3},
            {"tool": "done"},
        ]
    )
    outcome = _run(local_workspace, snapshot, provider)

    assert outcome.report.status is ToolLoopStatus.COMPLETE
    assert outcome.report.tool_calls == 1
    assert outcome.records, "the fixture contains 'timeout' in tracked files"
    tracked = set(local_workspace.ls_files())
    for record in outcome.records:
        assert record.path in tracked
        assert "timeout" in record.snippet.lower()
        revalidated = validate_retrieved_evidence(
            local_workspace,
            snapshot,
            path=record.path,
            start_line=record.start_line,
            end_line=record.end_line,
            kind=record.kind,
            rationale=record.rationale,
        )
        assert revalidated.ok, revalidated.reason
        assert revalidated.record.snippet == record.snippet


def test_fabricated_path_is_rejected_not_turned_into_evidence(
    local_workspace, snapshot
):
    provider = ScriptedProvider(
        [
            {"tool": "read_file", "path": "../outside.py", "start_line": 1, "end_line": 2},
            {"tool": "read_file", "path": "does/not/exist.py", "start_line": 1, "end_line": 2},
            {"tool": "done"},
        ]
    )
    outcome = _run(local_workspace, snapshot, provider)

    assert outcome.records == []
    assert outcome.report.records_added == 0
    assert [call.status for call in outcome.report.calls[:2]] == [
        "REJECTED",
        "REJECTED",
    ]
    assert outcome.report.tool_calls == 2


def test_inspect_manifest_is_read_only_and_cites_nothing(local_workspace, snapshot):
    provider = ScriptedProvider([{"tool": "inspect_manifest"}, {"tool": "done"}])
    outcome = _run(local_workspace, snapshot, provider)

    assert outcome.report.status is ToolLoopStatus.COMPLETE
    assert outcome.report.records_added == 0
    assert outcome.report.calls[0].tool is ToolName.INSPECT_MANIFEST
    assert outcome.report.calls[0].status == "OK"
    assert "tracked file" in outcome.report.calls[0].detail


def test_tool_call_cap_ends_as_partial_without_extra_model_call(
    local_workspace, snapshot
):
    provider = ScriptedProvider(
        [
            {"tool": "read_file", "path": "README.md", "start_line": 1, "end_line": 2},
            {"tool": "read_file", "path": "README.md", "start_line": 3, "end_line": 4},
            {"tool": "done"},
        ]
    )
    limits = ToolLoopLimits(max_tool_calls=2, max_seconds=10, max_total_bytes=100_000)
    outcome = _run(local_workspace, snapshot, provider, limits=limits)

    assert provider.calls == 2, "the loop must stop before another model call"
    assert outcome.report.status is ToolLoopStatus.PARTIAL
    assert outcome.report.tool_calls == 2
    assert [hit.limit.value for hit in outcome.report.limit_hits] == ["MAX_TOOL_CALLS"]
    assert "partial" in outcome.report.summary.lower()
    assert "not examined" in outcome.report.limit_hits[0].remaining_work


def test_byte_budget_ends_as_partial(local_workspace, snapshot):
    provider = ScriptedProvider(
        [
            {
                "tool": "read_file",
                "path": "src/fixture/core.py",
                "start_line": 1,
                "end_line": 4,
            },
        ]
    )
    limits = ToolLoopLimits(max_tool_calls=5, max_total_bytes=1, max_seconds=10)
    outcome = _run(local_workspace, snapshot, provider, limits=limits)

    assert outcome.report.status is ToolLoopStatus.PARTIAL
    assert outcome.report.bytes_read == 1
    assert [hit.limit.value for hit in outcome.report.limit_hits] == [
        "MAX_TOTAL_BYTES"
    ]
    assert "additional file content was not read" in (
        outcome.report.limit_hits[0].remaining_work
    )


def test_wall_clock_budget_ends_as_partial_before_any_model_call(
    local_workspace, snapshot
):
    provider = ScriptedProvider([{"tool": "done"}])
    limits = ToolLoopLimits(max_tool_calls=5, max_seconds=1e-9)
    outcome = _run(local_workspace, snapshot, provider, limits=limits)

    assert provider.calls == 0
    assert outcome.report.status is ToolLoopStatus.PARTIAL
    assert outcome.report.model_calls == 0
    assert [hit.limit.value for hit in outcome.report.limit_hits] == ["MAX_SECONDS"]


def test_invalid_model_output_is_recorded(local_workspace, snapshot):
    provider = ScriptedProvider(["this is not JSON"])
    outcome = _run(local_workspace, snapshot, provider)

    assert outcome.report.status is ToolLoopStatus.COMPLETE
    assert outcome.report.stop_reason == "invalid_model_output"
    assert outcome.report.calls[0].status == "ERROR"
    assert outcome.records == []


def test_shared_model_budget_charges_tool_loop_calls(local_workspace, snapshot):
    budget = ModelBudget(ModelBudgetLimits(max_calls=2, max_tokens=10_000))
    provider = ScriptedProvider(
        [
            {"tool": "read_file", "path": "README.md", "start_line": 1, "end_line": 2},
            {"tool": "done"},
        ]
    )
    outcome = _run(local_workspace, snapshot, provider, budget=budget)

    report = budget.report()
    assert report.calls == outcome.report.model_calls == 2
    assert report.usage_source == "reported"
    assert report.total_tokens == 30


def test_shared_model_budget_can_stop_the_loop(local_workspace, snapshot):
    budget = ModelBudget(ModelBudgetLimits(max_calls=1, max_tokens=10_000))
    provider = ScriptedProvider(
        [
            {"tool": "inspect_manifest"},
            {"tool": "done"},
        ]
    )
    with pytest.raises(ModelBudgetExceeded):
        _run(local_workspace, snapshot, provider, budget=budget)
    assert budget.calls == 1


class TestEvidenceValidation:
    def test_snippet_is_rebuilt_from_the_file(self, local_workspace, snapshot):
        result = validate_retrieved_evidence(
            local_workspace,
            snapshot,
            path="./README.md",
            start_line=1,
            end_line=2,
            kind=EvidenceKind.DOC,
            rationale="test",
        )
        assert result.ok
        actual = local_workspace.read_text("README.md").splitlines()[0:2]
        assert result.record.path == "README.md"
        assert result.record.snippet == "\n".join(actual)

    def test_untracked_path_is_rejected(self, local_workspace, snapshot):
        result = validate_retrieved_evidence(
            local_workspace,
            snapshot,
            path="missing.py",
            start_line=1,
            end_line=1,
            kind=EvidenceKind.SOURCE,
            rationale="test",
        )
        assert not result.ok
        assert "not a tracked file" in result.reason

    def test_path_traversal_is_rejected(self, local_workspace, snapshot):
        assert normalize_evidence_path("../outside.py") is None
        result = validate_retrieved_evidence(
            local_workspace,
            snapshot,
            path="../../etc/passwd",
            start_line=1,
            end_line=1,
            kind=EvidenceKind.SOURCE,
            rationale="test",
        )
        assert not result.ok
        assert "unsafe" in result.reason

    def test_out_of_range_lines_are_rejected(self, local_workspace, snapshot):
        result = validate_retrieved_evidence(
            local_workspace,
            snapshot,
            path="README.md",
            start_line=1,
            end_line=10_000,
            kind=EvidenceKind.DOC,
            rationale="test",
        )
        assert not result.ok
        assert "outside" in result.reason

    def test_blank_lines_are_rejected(self, local_workspace, snapshot):
        result = validate_retrieved_evidence(
            local_workspace,
            snapshot,
            path="README.md",
            start_line=2,
            end_line=2,
            kind=EvidenceKind.DOC,
            rationale="test",
        )
        assert not result.ok
        assert "empty" in result.reason

    def test_stale_commit_is_rejected(self, local_workspace, snapshot):
        stale = snapshot.model_copy(update={"commit_sha": "b" * 40})
        result = validate_retrieved_evidence(
            local_workspace,
            stale,
            path="README.md",
            start_line=1,
            end_line=2,
            kind=EvidenceKind.DOC,
            rationale="test",
        )
        assert not result.ok
        assert "no longer at the pinned commit" in result.reason
