"""Pipeline integration for the bounded model tool loop and model budget."""

import json
from pathlib import Path

from repomate_core.contracts import (
    ErrorCode,
    ModelBudgetLimits,
    RepositoryInput,
    RunStatus,
    TaskSource,
    ToolLoopLimits,
    ToolLoopStatus,
)
from repomate_core.models import ModelResult
from repomate_core.orchestration.pipeline import run_pipeline
from repomate_core.orchestration.pipeline_config import PipelineConfig
from repomate_core.orchestration.store import RunStore
from repomate_core.planning.model_planner import ModelPlanner
from repomate_core.repository.workspace import RepoWorkspace

PLAN = {
    "task_type": "DOCUMENTATION",
    "summary": "Document the timeout option in the README.",
    "planned_changes": [
        {
            "path": "README.md",
            "change_type": "MODIFY",
            "rationale": "document the timeout setting",
        }
    ],
    "acceptance_criteria": ["README mentions the timeout option"],
    "evidence_ids": ["ev1"],
    "limitations": [],
    "need_more_info": True,
    "questions": ["Which timeout value should be documented?"],
}

READ_CORE = {
    "tool": "read_file",
    "path": "src/fixture/core.py",
    "start_line": 1,
    "end_line": 4,
}


class ScriptedProvider:
    name = "fake"
    model_id = "fake-1"

    def __init__(self, responses: list[dict]) -> None:
        self._responses = list(responses)
        self.calls = 0

    def complete(self, **kwargs) -> ModelResult:
        self.calls += 1
        return ModelResult(
            text=json.dumps(self._responses.pop(0)),
            provider="fake",
            model="fake-1",
            usage={"prompt_tokens": 10, "completion_tokens": 5},
        )


def _factory(local_repo: Path):
    return lambda ref, dest, config: RepoWorkspace.from_local(local_repo)


def _config(
    tmp_path: Path,
    provider: ScriptedProvider,
    *,
    tool_limits: ToolLoopLimits | None = None,
    model_limits: ModelBudgetLimits | None = None,
) -> PipelineConfig:
    return PipelineConfig(
        runs_root=tmp_path / "runs",
        planner=ModelPlanner(provider),
        tool_limits=tool_limits or ToolLoopLimits(max_seconds=10),
        model_limits=model_limits or ModelBudgetLimits(max_calls=6, max_tokens=60_000),
    )


def _docs_input() -> RepositoryInput:
    return RepositoryInput(
        source=TaskSource.REPO_TASK,
        repo_url="https://github.com/acme/fixture-project",
        task="Add documentation for the timeout option to the README quickstart",
    )


def test_tool_loop_adds_validated_evidence_and_records_model_usage(
    tmp_path, local_repo
):
    provider = ScriptedProvider([READ_CORE, {"tool": "done"}, PLAN])
    config = _config(
        tmp_path,
        provider,
        tool_limits=ToolLoopLimits(max_tool_calls=2, max_seconds=10),
    )
    record = run_pipeline(
        _docs_input(), config=config, workspace_factory=_factory(local_repo)
    )

    assert record.status is RunStatus.NEED_MORE_INFO
    assert record.tool_loop is not None
    assert record.tool_loop.status is ToolLoopStatus.COMPLETE
    assert record.tool_loop.model_calls == 2
    assert record.tool_loop.tool_calls == 1
    assert record.tool_loop.records_added == 1
    assert record.tool_loop.rejected_items == 0
    assert any(r.path == "src/fixture/core.py" for r in record.evidence)

    assert record.model_usage is not None
    assert record.model_usage.calls == 3
    assert record.model_usage.usage_source == "reported"
    assert record.model_usage.total_tokens == 45

    persisted = RunStore(tmp_path / "runs").load_run(record.run_id)
    assert persisted.tool_loop is not None
    assert persisted.model_usage is not None
    assert persisted.model_usage.calls == 3
    assert not RunStore(tmp_path / "runs").workspace_dir(record.run_id).exists()


def test_tool_budget_hit_ends_as_partial_without_planning(tmp_path, local_repo):
    provider = ScriptedProvider([READ_CORE])
    config = _config(
        tmp_path,
        provider,
        tool_limits=ToolLoopLimits(max_tool_calls=1, max_seconds=10),
    )
    record = run_pipeline(
        _docs_input(), config=config, workspace_factory=_factory(local_repo)
    )

    assert record.status is RunStatus.PARTIAL
    assert record.plan is None
    assert record.artifact is None
    assert record.receipt is None
    assert record.tool_loop is not None
    assert record.tool_loop.status is ToolLoopStatus.PARTIAL
    assert [hit.limit.value for hit in record.tool_loop.limit_hits] == [
        "MAX_TOOL_CALLS"
    ]
    assert record.model_usage is not None
    assert record.model_usage.calls == 1
    # The partial run still publishes the evidence it did validate.
    assert any(r.path == "src/fixture/core.py" for r in record.evidence)

    persisted = RunStore(tmp_path / "runs").load_run(record.run_id)
    assert persisted.status is RunStatus.PARTIAL
    assert persisted.tool_loop.status is ToolLoopStatus.PARTIAL


def test_exhausted_model_budget_fails_with_budget_exceeded(tmp_path, local_repo):
    provider = ScriptedProvider([READ_CORE])
    config = _config(
        tmp_path,
        provider,
        tool_limits=ToolLoopLimits(max_tool_calls=4, max_seconds=10),
        model_limits=ModelBudgetLimits(max_calls=1, max_tokens=60_000),
    )
    record = run_pipeline(
        _docs_input(), config=config, workspace_factory=_factory(local_repo)
    )

    assert record.status is RunStatus.FAILED
    assert record.error is not None
    assert record.error.code is ErrorCode.BUDGET_EXCEEDED
    assert record.model_usage is not None
    assert record.model_usage.calls == 1
    assert record.model_usage.exhausted is True


def test_heuristic_runs_skip_the_tool_loop(tmp_path, local_repo):
    run_input = RepositoryInput(
        source=TaskSource.REPO_TASK,
        repo_url="https://github.com/acme/fixture-project",
        task="fix the crash in the parser when items is empty",
    )
    record = run_pipeline(
        run_input,
        config=PipelineConfig(runs_root=tmp_path / "runs"),
        workspace_factory=_factory(local_repo),
    )

    assert record.status is RunStatus.NEED_MORE_INFO
    assert record.planner == "heuristic-v1"
    assert record.tool_loop is None
    assert record.model_usage is None
