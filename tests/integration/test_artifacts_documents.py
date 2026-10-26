"""End-to-end artifact documents: plan, checklist and TEST_DIFF.

These tests use a deterministic scripted provider (the same contract a live
model fulfils) so they run without network access. The verification sandbox
may fall back to NOT_RUN on hosts without an egress backend; artifact
generation and persistence must still work.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from repomate_core.contracts import (
    ArtifactKind,
    RepositoryInput,
    RunStatus,
    TaskSource,
    TaskType,
)
from repomate_core.models import ModelResult
from repomate_core.orchestration.pipeline import run_pipeline
from repomate_core.orchestration.pipeline_config import PipelineConfig
from repomate_core.orchestration.store import RunStore
from repomate_core.planning.model_planner import ModelPlanner
from repomate_core.repository.workspace import RepoWorkspace


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


def _config(tmp_path: Path, provider: ScriptedProvider) -> PipelineConfig:
    return PipelineConfig(
        runs_root=tmp_path / "runs",
        planner=ModelPlanner(provider),
    )


def _input(task: str) -> RepositoryInput:
    return RepositoryInput(
        source=TaskSource.REPO_TASK,
        repo_url="https://github.com/acme/fixture-project",
        task=task,
    )


def _test_plan() -> dict:
    return {
        "task_type": "TEST",
        "summary": "Add a regression test for the empty-input case.",
        "planned_changes": [
            {
                "path": "tests/test_timeout.py",
                "change_type": "CREATE",
                "rationale": "cover the timeout default",
            }
        ],
        "acceptance_criteria": ["A regression test covers an empty input list"],
        "evidence_ids": ["ev1"],
        "limitations": [],
        "need_more_info": False,
        "questions": [],
        "proposed_edits": [
            {
                "path": "tests/test_timeout.py",
                "old_text": "",
                "new_text": (
                    "from fixture.core import process\n\n\n"
                    "def test_process_empty_input():\n"
                    "    assert process([]) == []\n"
                ),
                "rationale": "regression coverage",
            }
        ],
    }


def _bug_plan() -> dict:
    return {
        "task_type": "BUG_FIX",
        "summary": "Guard the parser against an empty items list.",
        "planned_changes": [
            {
                "path": "src/fixture/core.py",
                "change_type": "MODIFY",
                "rationale": "empty input reaches process()",
            }
        ],
        "acceptance_criteria": ["process([]) returns an empty list"],
        "evidence_ids": ["ev1"],
        "limitations": [],
        "need_more_info": False,
        "questions": [],
        "proposed_edits": [
            {
                "path": "src/fixture/core.py",
                "old_text": "def process(items, timeout=30):\n",
                "new_text": (
                    "def process(items, timeout=30):\n"
                    "    if not items:\n"
                    "        return []\n"
                ),
                "rationale": "empty input should not reach transform",
            }
        ],
    }


def _feature_or_refactor_plan(task_type: str) -> dict:
    return {
        "task_type": task_type,
        "summary": "Raise the default timeout for long-running transforms.",
        "planned_changes": [
            {
                "path": "src/fixture/core.py",
                "change_type": "MODIFY",
                "rationale": "the current default is too short for large inputs",
            }
        ],
        "acceptance_criteria": ["the default timeout is doubled"],
        "evidence_ids": ["ev1"],
        "limitations": [],
        "need_more_info": False,
        "questions": [],
        "proposed_edits": [
            {
                "path": "src/fixture/core.py",
                "old_text": "def process(items, timeout=30):\n",
                "new_text": "def process(items, timeout=60):\n",
                "rationale": "double the default timeout",
            }
        ],
    }


def test_test_task_produces_test_diff_and_plan_document(tmp_path, local_repo):
    provider = ScriptedProvider([{"tool": "done"}, _test_plan()])
    record = run_pipeline(
        _input("add a regression test for timeout handling"),
        config=_config(tmp_path, provider),
        workspace_factory=_factory(local_repo),
    )

    assert record.status is RunStatus.COMPLETED, record.error
    assert record.plan is not None and record.plan.task_type is TaskType.TEST
    assert record.artifact is not None
    assert record.artifact.kind is ArtifactKind.TEST_DIFF
    assert record.artifact.affected_paths == ["tests/test_timeout.py"]
    assert [doc.name for doc in record.documents] == ["CONTRIBUTION_PLAN.md"]
    plan_doc = record.documents[0]
    assert plan_doc.kind is ArtifactKind.CONTRIBUTION_PLAN
    assert "TEST" in plan_doc.content
    assert "tests/test_timeout.py" in plan_doc.content
    assert "## Evidence consulted" in plan_doc.content

    persisted = RunStore(tmp_path / "runs").load_run(record.run_id)
    assert persisted.documents == record.documents
    assert persisted.artifact.kind is ArtifactKind.TEST_DIFF


def test_bug_task_publishes_plan_and_repro_checklist(tmp_path, local_repo):
    provider = ScriptedProvider([{"tool": "done"}, _bug_plan()])
    record = run_pipeline(
        _input("fix the crash when process receives an empty list"),
        config=_config(tmp_path, provider),
        workspace_factory=_factory(local_repo),
    )

    assert record.status is RunStatus.COMPLETED, record.error
    assert record.artifact is not None
    assert record.artifact.kind is ArtifactKind.PATCH_DIFF
    names = [doc.name for doc in record.documents]
    assert names == ["CONTRIBUTION_PLAN.md", "REPRO_CHECKLIST.md"]
    checklist = record.documents[1]
    assert checklist.kind is ArtifactKind.REPRO_CHECKLIST
    assert "did not observe the reported failure" in checklist.content
    assert "Verification recorded by RepoMate" in checklist.content
    assert "post-patch" in checklist.content.lower()

    persisted = RunStore(tmp_path / "runs").load_run(record.run_id)
    assert [doc.name for doc in persisted.documents] == names


@pytest.mark.parametrize("task_type", ["FEATURE", "REFACTOR"])
def test_feature_and_refactor_plans_produce_patch_diff(
    task_type, tmp_path, local_repo
):
    provider = ScriptedProvider([{"tool": "done"}, _feature_or_refactor_plan(task_type)])
    record = run_pipeline(
        _input("raise the default timeout for long-running transforms"),
        config=_config(tmp_path, provider),
        workspace_factory=_factory(local_repo),
    )

    assert record.status is RunStatus.COMPLETED, record.error
    assert record.plan is not None
    assert record.plan.task_type.value == task_type
    assert record.artifact is not None
    assert record.artifact.kind is ArtifactKind.PATCH_DIFF
    assert record.artifact.affected_paths == ["src/fixture/core.py"]
    assert [doc.name for doc in record.documents] == ["CONTRIBUTION_PLAN.md"]


def test_need_more_info_bug_still_publishes_plan_and_checklist(tmp_path, local_repo):
    plan = _bug_plan()
    plan["need_more_info"] = True
    plan["proposed_edits"] = []
    plan["questions"] = ["Which input shape triggers the crash?"]
    provider = ScriptedProvider([{"tool": "done"}, plan])
    record = run_pipeline(
        _input("fix the crash when process receives an empty list"),
        config=_config(tmp_path, provider),
        workspace_factory=_factory(local_repo),
    )

    assert record.status is RunStatus.NEED_MORE_INFO
    assert record.artifact is None
    names = [doc.name for doc in record.documents]
    assert names == ["CONTRIBUTION_PLAN.md", "REPRO_CHECKLIST.md"]
    assert "Which input shape triggers the crash?" in record.documents[1].content


def test_artifact_listing_and_downloads(tmp_path, local_repo, monkeypatch):
    provider = ScriptedProvider([{"tool": "done"}, _test_plan()])
    record = run_pipeline(
        _input("add a regression test for timeout handling"),
        config=_config(tmp_path, provider),
        workspace_factory=_factory(local_repo),
    )
    assert record.documents and record.artifact is not None

    monkeypatch.setenv("REPOMATE_RUNS_ROOT", str(tmp_path / "runs"))
    monkeypatch.setenv("OLLAMA_API_KEY", "")
    from services.api import main as api_module

    client = TestClient(api_module.app)

    listing = client.get(f"/api/runs/{record.run_id}/artifacts")
    assert listing.status_code == 200, listing.text
    items = listing.json()
    assert {item["name"] for item in items} == {
        "tests.patch",
        "CONTRIBUTION_PLAN.md",
    }
    patch_item = next(item for item in items if item["name"] == "tests.patch")
    assert patch_item["kind"] == "TEST_DIFF"
    assert patch_item["download_url"].endswith("/artifacts/patch")

    patch = client.get(patch_item["download_url"])
    assert patch.status_code == 200
    assert "diff --git" in patch.text
    assert "tests.patch" in patch.headers["content-disposition"]
    assert patch.headers["x-content-type-options"] == "nosniff"
    assert patch.headers["content-type"].startswith("text/x-diff")

    plan = client.get(f"/api/runs/{record.run_id}/artifacts/CONTRIBUTION_PLAN.md")
    assert plan.status_code == 200
    assert plan.headers["content-type"].startswith("text/markdown")
    assert "Contribution Plan" in plan.text
    assert "attachment" in plan.headers["content-disposition"]
    assert plan.headers["x-content-type-options"] == "nosniff"

    missing = client.get(f"/api/runs/{record.run_id}/artifacts/UNKNOWN.md")
    assert missing.status_code == 404
    unknown_run = client.get("/api/runs/run_missing/artifacts")
    assert unknown_run.status_code == 404
