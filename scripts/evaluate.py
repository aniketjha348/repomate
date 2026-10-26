"""PS04 evaluation harness.

Runs the docs/evaluation.md task matrix against local fixtures (plus
simulated failure injections) and writes docs/evaluation-results.md with
the actual outcomes. Deterministic, hermetic, no network required.

Usage:  python scripts/evaluate.py
"""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

# Hermetic by contract: the matrix asserts deterministic heuristic-planner
# outcomes, so a developer's local ``.env`` (which may configure a model
# gateway) must not leak into it.
os.environ["REPOMATE_SKIP_DOTENV"] = "1"

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "packages"))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from repomate_core.contracts import (
    ContributionPlan,
    ErrorCode,
    PlannedChange,
    ProposedEdit,
    RepositoryInput,
    RetrievalLimits,
    RunStatus,
    TaskSource,
    TaskType,
)
from repomate_core.models import ModelError
from repomate_core.orchestration.pipeline import run_pipeline
from repomate_core.orchestration.pipeline_config import PipelineConfig
from repomate_core.repository.errors import RateLimitedError
from repomate_core.repository.workspace import RepoWorkspace

ROOT = Path(__file__).resolve().parent.parent

FIXTURE_FILES = {
    "readme.md": "# fixture\n\n## Quickstart\n\npip install fixture-project.\n\n## Configuration\n\nFIXTURE_TIMEOUT controls the request timeout.\n",
    "license": "MIT License\n\nPermission is hereby granted, free of charge, to any person obtaining a copy\nof this software and associated documentation files.\n",
    "pyproject.toml": "[project]\nname='fixture-project'\nversion='0.1.0'\n\n[tool.pytest.ini_options]\npythonpath=['src']\n",
    "src/fixture/__init__.py": "",
    "src/fixture/core.py": "def process(items, timeout=30):\n    return [str(i).lower() for i in items]\n",
    "tests/test_core.py": "from fixture.core import process\n\ndef test_process():\n    assert process(['A']) == ['a']\n",
}


def _git(cwd: Path, *args: str) -> None:
    env = dict(
        os.environ,
        GIT_AUTHOR_NAME="Eval",
        GIT_AUTHOR_EMAIL="eval@invalid",
        GIT_COMMITTER_NAME="Eval",
        GIT_COMMITTER_EMAIL="eval@invalid",
    )
    result = subprocess.run(
        ["git", *args], cwd=str(cwd), capture_output=True, text=True, env=env
    )
    assert result.returncode == 0, result.stderr


def build_fixture(root: Path, files: dict[str, str] | None = None) -> RepoWorkspace:
    repo = root / "fixture-project"
    for rel, content in (files or FIXTURE_FILES).items():
        target = repo / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8", newline="\n")
    _git(repo, "init", "-b", "main")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-m", "fixture")
    return RepoWorkspace.from_local(repo)


def _factory(workspace: RepoWorkspace):
    return lambda ref, dest, config: workspace


def _config(root: Path, **overrides) -> PipelineConfig:
    defaults = dict(runs_root=root / "runs", keep_workspace=False)
    defaults.update(overrides)
    return PipelineConfig(**defaults)


class StaticPlanner:
    """Evaluation-only planner with a fixed, reviewable plan.

    Used where a model planner is required to prove artifact generation but
    the matrix must stay hermetic. It is deliberately *not* a ModelPlanner, so
    the bounded model tool loop is skipped and no gateway call is implied.
    """

    def __init__(self, plan: ContributionPlan) -> None:
        self.name = "scripted-eval-v1"
        self._plan = plan

    def plan(self, task_text, snapshot, evidence):
        return self._plan.model_copy(deep=True)


def _bug_plan(*, regression: bool = False) -> ContributionPlan:
    replacement = (
        "def process(items, timeout=30):\n"
        "    return [str(i).upper() for i in items]\n"
        if regression
        else "def process(items, timeout=30):\n"
        "    if not items:\n"
        "        return []\n"
        "    return [str(i).lower() for i in items]\n"
    )
    return ContributionPlan(
        task_type=TaskType.BUG_FIX,
        summary="Guard process() against an empty items list.",
        planned_changes=[
            PlannedChange(
                path="src/fixture/core.py",
                change_type="MODIFY",
                rationale="the parser receives an empty list",
            )
        ],
        acceptance_criteria=["process([]) returns an empty list"],
        evidence_ids=["ev1"],
        planned_by="scripted-eval-v1",
        proposed_edits=[
            ProposedEdit(
                path="src/fixture/core.py",
                old_text=(
                    "def process(items, timeout=30):\n"
                    "    return [str(i).lower() for i in items]\n"
                ),
                new_text=replacement,
                rationale="guard the empty input path",
            )
        ],
    )


def _test_plan() -> ContributionPlan:
    return ContributionPlan(
        task_type=TaskType.TEST,
        summary="Add a regression test for empty process() input.",
        planned_changes=[
            PlannedChange(
                path="tests/test_timeout_regression.py",
                change_type="CREATE",
                rationale="cover the empty-input path",
            )
        ],
        acceptance_criteria=["a regression test exercises process([])"],
        evidence_ids=["ev1"],
        planned_by="scripted-eval-v1",
        proposed_edits=[
            ProposedEdit(
                path="tests/test_timeout_regression.py",
                old_text="",
                new_text=(
                    "from fixture.core import process\n\n\n"
                    "def test_process_empty_input():\n"
                    "    assert process([]) == []\n"
                ),
                rationale="regression coverage",
            )
        ],
    )


def _run(root: Path, task: str, *, workspace: RepoWorkspace, **config_overrides):
    run_input = RepositoryInput(
        source=TaskSource.REPO_TASK,
        repo_url="https://github.com/acme/fixture-project",
        task=task,
    )
    return run_pipeline(
        run_input,
        config=_config(root, **config_overrides),
        workspace_factory=_factory(workspace),
    )


def _summary(record) -> str:
    bits = [f"status={record.status.value}"]
    if record.error:
        bits.append(f"error={record.error.code.value}")
    if record.receipt:
        bits.append(f"overall={record.receipt.overall.value}")
        suite = next(
            (c for c in record.receipt.checks if c.name == "repository-test-suite"), None
        )
        if suite:
            bits.append(f"suite={suite.status.value}")
        comparison = record.receipt.comparison
        if comparison:
            bits.append(
                f"comparison={comparison.outcome.value}"
                f"({comparison.baseline.status.value}->"
                f"{comparison.post_patch.status.value})"
            )
    if record.retrieval:
        bits.append(f"retrieval={record.retrieval.status.value}")
    if record.artifact:
        bits.append(f"artifact={record.artifact.kind.value}")
        bits.append(f"planner={record.artifact.generated_by}")
        bits.append(f"paths={','.join(record.artifact.affected_paths)}")
    if record.documents:
        bits.append("documents=" + ",".join(doc.name for doc in record.documents))
    if record.plan and record.plan.need_more_info:
        bits.append("questions=yes")
    return " · ".join(bits)


def scenario_documentation_task(root: Path):
    workspace = build_fixture(root / "s1")
    record = _run(root, "Add documentation for the timeout option to the README", workspace=workspace)
    expected = "COMPLETED, docs diff, patch checks PASSED, fixture suite PASSED"
    ok = (
        record.status is RunStatus.COMPLETED
        and record.artifact is not None
        and all(
            c.status.value == "PASSED"
            for c in record.receipt.checks
            if c.name != "repository-test-suite"
        )
    )
    return expected, _summary(record), ok


def scenario_bug_task(root: Path):
    workspace = build_fixture(root / "s2")
    record = _run(
        root,
        "fix the crash in the parser when items is empty",
        workspace=workspace,
        planner=StaticPlanner(_bug_plan()),
    )
    expected = "COMPLETED, PATCH_DIFF + CONTRIBUTION_PLAN.md + REPRO_CHECKLIST.md"
    ok = (
        record.status is RunStatus.COMPLETED
        and record.artifact is not None
        and record.artifact.kind.value == "PATCH_DIFF"
        and {doc.name for doc in record.documents}
        == {"CONTRIBUTION_PLAN.md", "REPRO_CHECKLIST.md"}
    )
    return expected, _summary(record), ok


def scenario_test_task(root: Path):
    workspace = build_fixture(root / "s3")
    record = _run(
        root,
        "add a regression test for timeout handling",
        workspace=workspace,
        planner=StaticPlanner(_test_plan()),
    )
    expected = "COMPLETED, TEST_DIFF + CONTRIBUTION_PLAN.md"
    ok = (
        record.status is RunStatus.COMPLETED
        and record.artifact is not None
        and record.artifact.kind.value == "TEST_DIFF"
        and [doc.name for doc in record.documents] == ["CONTRIBUTION_PLAN.md"]
    )
    return expected, _summary(record), ok


def scenario_ambiguous_task(root: Path):
    workspace = build_fixture(root / "s4")
    record = _run(root, "make it better somehow", workspace=workspace)
    ok = (
        record.status is RunStatus.NEED_MORE_INFO
        and bool(record.plan.questions)
        and [doc.name for doc in record.documents] == ["CONTRIBUTION_PLAN.md"]
    )
    return "NEED_MORE_INFO with explicit questions + downloadable plan", _summary(record), ok


def scenario_missing_license(root: Path):
    files = {
        key: value for key, value in FIXTURE_FILES.items() if key != "license"
    }
    workspace = build_fixture(root / "s_license", files)
    record = _run(
        root,
        "document the timeout option in the readme",
        workspace=workspace,
    )
    license_status = (
        record.snapshot.license.status.value if record.snapshot is not None else "none"
    )
    plan_doc = next(
        (doc for doc in record.documents if doc.name == "CONTRIBUTION_PLAN.md"), None
    )
    ok = (
        record.status is RunStatus.COMPLETED
        and license_status == "ABSENT"
        and plan_doc is not None
        and "**License:** `ABSENT`" in plan_doc.content
    )
    return "license ABSENT surfaced in run and plan document", _summary(record), ok


def scenario_large_repository_partial(root: Path):
    files = dict(FIXTURE_FILES)
    for index in range(40):
        files[f"src/fixture/module_{index:02d}.py"] = (
            f"def helper_{index}(value):\n"
            f"    \"\"\"timeout helper {index}.\"\"\"\n"
            f"    return value\n"
        )
    workspace = build_fixture(root / "s_large", files)
    record = _run(
        root,
        "document the timeout option in the readme",
        workspace=workspace,
        retrieval_limits=RetrievalLimits(max_files=1),
    )
    ok = (
        record.status is RunStatus.PARTIAL
        and record.retrieval is not None
        and record.retrieval.status.value == "PARTIAL"
        and record.artifact is None
        and record.plan is None
    )
    return "PARTIAL with remaining retrieval work; no plan or patch", _summary(record), ok


def scenario_potential_regression(root: Path):
    workspace = build_fixture(root / "s_regression")
    record = _run(
        root,
        "fix the crash in the parser when items is empty",
        workspace=workspace,
        planner=StaticPlanner(_bug_plan(regression=True)),
    )
    comparison = record.receipt.comparison if record.receipt else None
    outcome = comparison.outcome.value if comparison else "none"
    # The sandbox backend may be unavailable on the host. Either way the
    # receipt must refuse to call this a success: the outcome must be a
    # regression or an explicitly incomplete comparison.
    ok = (
        record.status is RunStatus.COMPLETED
        and outcome
        in {
            "POTENTIAL_REGRESSION",
            "BASELINE_INCOMPLETE",
            "POST_PATCH_INCOMPLETE",
        }
    )
    return "POTENTIAL_REGRESSION/INCOMPLETE, never presented as fixed", _summary(record), ok


def scenario_network_attempt(root: Path):
    files = dict(FIXTURE_FILES)
    files["tests/test_egress.py"] = (
        "import socket\n\n"
        "def test_network_is_denied():\n"
        "    socket.create_connection(('1.1.1.1', 80), timeout=2)\n"
    )
    workspace = build_fixture(root / "s_network", files)
    record = _run(
        root,
        "document the timeout option in the readme",
        workspace=workspace,
    )
    suite = next(
        (c for c in record.receipt.checks if c.name == "repository-test-suite"),
        None,
    ) if record.receipt else None
    sandbox = record.receipt.sandbox if record.receipt else None
    # With an egress backend the suite must FAIL while the sandbox records a
    # verified policy. Without a backend the suite must be refused (NOT_RUN),
    # never run with network access.
    backend_verified = bool(sandbox and sandbox.policy_enforced)
    ok = (
        record.status is RunStatus.COMPLETED
        and suite is not None
        and sandbox is not None
        and (
            (backend_verified and suite.status.value == "FAILED")
            or (
                not backend_verified
                and suite.status.value == "NOT_RUN"
                and sandbox.egress_validation in {"NOT_ENFORCED", "FAILED"}
                and any(
                    word in suite.reason.lower()
                    for word in ("sandbox", "network", "egress")
                )
            )
        )
    )
    return "network attempt blocked; suite FAILED or refused NOT_RUN", _summary(record), ok


def scenario_unsupported_toolchain(root: Path):
    files = {
        "readme.md": "# no toolchain\n\nInstallation: copy the files manually onto the server.\n",
        "license": FIXTURE_FILES["license"],
    }
    workspace = build_fixture(root / "s5", files)
    record = _run(root, "document the installation steps in the readme", workspace=workspace)
    suite = next(c for c in record.receipt.checks if c.name == "repository-test-suite")
    ok = suite.status.value == "NOT_RUN" and "no recognized test command" in suite.reason
    return "suite NOT_RUN with reason (no supported toolchain)", _summary(record), ok


def scenario_failing_suite(root: Path):
    files = dict(FIXTURE_FILES)
    files["tests/test_core.py"] = (
        "from fixture.core import process\n\ndef test_broken():\n    assert process(['A']) == ['nope']\n"
    )
    workspace = build_fixture(root / "s6", files)
    record = _run(root, "document the retry option in the readme", workspace=workspace)
    suite = next(c for c in record.receipt.checks if c.name == "repository-test-suite")
    ok = record.status is RunStatus.COMPLETED and suite.status.value == "FAILED"
    return "COMPLETED with honest FAILED suite check", _summary(record), ok


def scenario_malformed_urls(root: Path):
    workspace = build_fixture(root / "s7")
    outcomes = []
    for bad in (
        "http://github.com/a/b",
        "https://evil.com/a/b",
        "https://github.com/a/b/pull/1",
        "not a url",
    ):
        run_input = RepositoryInput(
            source=TaskSource.REPO_TASK, repo_url=bad, task="document it"
        )
        record = run_pipeline(
            run_input, config=_config(root), workspace_factory=_factory(workspace)
        )
        outcomes.append(record.error.code.value if record.error else "none")
    ok = all(code == "INVALID_INPUT" for code in outcomes)
    return "typed INVALID_INPUT for every malformed URL", "errors=" + ",".join(outcomes), ok


def scenario_missing_repo(root: Path):
    def exploding(ref, dest, config):
        from repomate_core.repository.errors import WorkspaceError

        raise WorkspaceError("git clone failed (exit 128): repository not found")

    run_input = RepositoryInput(
        source=TaskSource.REPO_TASK,
        repo_url="https://github.com/acme/ghost-repo-xyz",
        task="document the ghost",
    )
    record = run_pipeline(run_input, config=_config(root), workspace_factory=exploding)
    ok = record.status is RunStatus.FAILED and record.error.code is ErrorCode.NETWORK
    return "typed NETWORK_ERROR", _summary(record), ok


def scenario_rate_limited(root: Path, monkeypatch_fetch):
    monkeypatch_fetch(RateLimitedError("GitHub API rate limit exhausted"))
    workspace = build_fixture(root / "s8")
    run_input = RepositoryInput(
        source=TaskSource.GITHUB_ISSUE,
        issue_url="https://github.com/acme/fixture-project/issues/1",
    )
    record = run_pipeline(
        run_input, config=_config(root), workspace_factory=_factory(workspace)
    )
    ok = record.status is RunStatus.FAILED and record.error.code is ErrorCode.RATE_LIMITED
    return "typed RATE_LIMITED (simulated)", _summary(record), ok


def scenario_model_failure(root: Path):
    class ExplodingPlanner:
        name = "model:openai/gemma4:31b"

        def plan(self, task_text, snapshot, evidence):
            raise ModelError("gateway 503 after retries")

    workspace = build_fixture(root / "s9")
    record = _run(
        root,
        "Add documentation for the timeout option to the README",
        workspace=workspace,
        planner=ExplodingPlanner(),
    )
    ok = record.status is RunStatus.FAILED and record.error.code is ErrorCode.MODEL
    return "typed MODEL_ERROR (simulated gateway failure)", _summary(record), ok


def _patch_fetch_issue(exc: Exception):
    from repomate_core.orchestration import stages as stages_module

    original = stages_module.fetch_issue

    def fetch_issue(ref, **kwargs):
        raise exc

    stages_module.fetch_issue = fetch_issue
    return lambda: setattr(stages_module, "fetch_issue", original)


def main() -> int:
    scenarios = [
        ("1", "Documentation task (fixture)", scenario_documentation_task),
        ("2", "Bug fix with relevant test", scenario_bug_task),
        ("3", "Test-addition task", scenario_test_task),
        ("4", "Ambiguous task", scenario_ambiguous_task),
        ("5", "Large repository (retrieval limit)", scenario_large_repository_partial),
        ("6", "Missing license", scenario_missing_license),
        ("7", "Unsupported toolchain", scenario_unsupported_toolchain),
        ("7b", "Failing repository suite", scenario_failing_suite),
        ("8", "Network attempt (malicious repo)", scenario_network_attempt),
        ("9", "GitHub rate limit (simulated)", None),  # patched below
        ("9b", "Model gateway failure (simulated)", scenario_model_failure),
        ("10", "Potential regression", scenario_potential_regression),
        ("11", "Malformed URLs", scenario_malformed_urls),
        ("12", "Nonexistent repository", scenario_missing_repo),
    ]

    rows: list[tuple[str, str, str, bool]] = []
    with tempfile.TemporaryDirectory(prefix="repomate-eval-") as tmp:
        root = Path(tmp)
        for number, name, fn in scenarios:
            if fn is None:  # rate limit needs the monkeypatch dance
                restore = _patch_fetch_issue(RateLimitedError("rate limit exhausted"))
                try:
                    expected, actual, ok = scenario_rate_limited(root, lambda e: None)
                finally:
                    restore()
            else:
                expected, actual, ok = fn(root)
            rows.append((number, name, expected, actual, ok))

    lines = [
        "# PS04 Evaluation Results",
        "",
        f"Generated {datetime.now(timezone.utc).isoformat()} by `scripts/evaluate.py` "
        "(deterministic, hermetic; rate-limit and model failures are simulated injections).",
        "",
        "| # | Scenario | Expected | Actual outcome | Pass |",
        "|---|----------|----------|----------------|------|",
    ]
    for number, name, expected, actual, ok in rows:
        lines.append(f"| {number} | {name} | {expected} | `{actual}` | {'✅' if ok else '❌'} |")
    lines += [
        "",
        "Rows 1–2 of docs/evaluation.md (live GitHub runs) are covered by the opt-in",
        "network e2e test (`pytest -m network tests/e2e/test_live_github.py`) and the",
        "browser-to-artifact evidence in",
        "`docs/evaluation-runs/browser_tabulate_481/`; the public-repository",
        "results are summarized in `docs/evaluation-real-results.md`.",
        "",
    ]

    output = ROOT / "docs" / "evaluation-results.md"
    output.write_text("\n".join(lines), encoding="utf-8", newline="\n")
    print(f"wrote {output}")
    failures = [row for row in rows if not row[4]]
    if failures:
        print(f"FAILURES: {[f[1] for f in failures]}")
        return 1
    print("all scenarios passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
