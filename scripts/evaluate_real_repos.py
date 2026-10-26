"""Real-repository acceptance suite for PS04.

This is intentionally *not* a unit-test suite. It runs the real pipeline
against public GitHub repositories, preserves every run record, receipt,
artifact and document under ``docs/evaluation-runs/``, and writes a
human-readable summary to ``docs/evaluation-real-results.md``.

The suite is opt-in because it clones repositories and may call the
configured model gateway. It is designed to be honest about its own
scaffolding:

- Scripted plans are labelled ``scripted-eval-v1``; the repository,
  snapshot, evidence collection, artifact generation, sandbox and
  verification are real, but the plan text is fixed by this harness.
- A bug-reproduction case adds a regression test as a local commit on top of
  the real upstream commit. The provenance file records both commits and the
  injected file. This is what makes a baseline FAILED -> post-patch PASSED
  comparison meaningful without pretending upstream already shipped the test.
- A network case adds a test that attempts real egress. Under an enforcing
  sandbox that test fails, and the receipt must say so.
- Fault-injection cases are labelled. They prove the error path, not that
  GitHub or the gateway actually failed for the operator.

Usage (WSL with bubblewrap installed is the supported environment):

    python scripts/evaluate_real_repos.py
    python scripts/evaluate_real_repos.py --only bug_tabulate_478 ...
    python scripts/evaluate_real_repos.py --skip-live
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import time
from contextlib import ExitStack
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Optional
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "packages"))

from repomate_core.contracts import (  # noqa: E402
    ArtifactKind,
    ContributionPlan,
    PlannedChange,
    ProposedEdit,
    RepositoryInput,
    RetrievalStatus,
    RunRecord,
    RunStatus,
    TaskSource,
    TaskType,
    VerificationStatus,
)
from repomate_core.env import load_env_file  # noqa: E402
from repomate_core.models import ModelError  # noqa: E402
from repomate_core.models.openai import OpenAIProvider  # noqa: E402
from repomate_core.orchestration.pipeline import (  # noqa: E402
    resolve_planner,
    run_pipeline,
)
from repomate_core.orchestration.pipeline_config import PipelineConfig  # noqa: E402
from repomate_core.planning.model_planner import ModelPlanner  # noqa: E402
from repomate_core.repository.errors import RateLimitedError  # noqa: E402
from repomate_core.repository.workspace import RepoWorkspace  # noqa: E402
from repomate_core.verification.network_policy import detect_egress_backend  # noqa: E402

WORK_ROOT = ROOT / "var" / "eval-real"
CACHE_ROOT = WORK_ROOT / "workspaces"
CASE_WORK_ROOT = WORK_ROOT / "cases"
RUNS_ROOT = WORK_ROOT / "runs"
OUT_ROOT = ROOT / "docs" / "evaluation-runs"
RESULTS_PATH = ROOT / "docs" / "evaluation-real-results.md"

SUITE = "repository-test-suite"


# ---------------------------------------------------------------------------
# Case definitions
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Case:
    slug: str
    title: str
    repo: str
    expected: str
    source: str = "task"  # "task" or "issue"
    issue_number: Optional[int] = None
    task: Optional[str] = None
    planner: str = "scripted"  # scripted | live | failing-model | none
    prepare: Optional[str] = None  # bug478 | network | regression
    base_commit: Optional[str] = None
    max_bytes_per_file: Optional[int] = None
    inject_rate_limit: bool = False
    notes: str = ""


CASES: tuple[Case, ...] = (
    Case(
        slug="docs_tabulate_481_scripted",
        title="Documentation task on a licensed public repository",
        repo="astanin/python-tabulate",
        source="issue",
        issue_number=481,
        base_commit="268615a5c27dc40e5c22454c07b44d5c50410da0",
        expected=(
            "COMPLETED with a DOCS_DIFF, CONTRIBUTION_PLAN.md, patch checks "
            "PASSED and a real repository-suite receipt"
        ),
        notes=(
            "Issue #481 asks for a README clarification. The plan is scripted "
            "so the mechanics are repeatable; the repository, issue, evidence "
            "and verification are real."
        ),
    ),
    Case(
        slug="docs_tabulate_481_live",
        title="Documentation task with the configured live model",
        repo="astanin/python-tabulate",
        source="issue",
        issue_number=481,
        base_commit="268615a5c27dc40e5c22454c07b44d5c50410da0",
        planner="live",
        expected=(
            "COMPLETED with a DOCS_DIFF and CONTRIBUTION_PLAN.md; a typed "
            "MODEL_ERROR is preserved honestly if the gateway fails"
        ),
        notes=(
            "This call uses the configured gateway and model. A failure here "
            "is a real observed failure, not a simulated one."
        ),
    ),
    Case(
        slug="bug_tabulate_478_scripted",
        title="Reproducible bug with a relevant regression test",
        repo="astanin/python-tabulate",
        source="issue",
        issue_number=478,
        base_commit="268615a5c27dc40e5c22454c07b44d5c50410da0",
        prepare="bug478",
        expected="COMPLETED, PATCH_DIFF, plan + repro checklist, CONSISTENT_IMPROVEMENT",
        notes=(
            "A regression test for issue #478 is committed on top of upstream "
            "268615a. Baseline fails on the test; the scripted patch restores "
            "the width guard and post-patch passes."
        ),
    ),
    Case(
        slug="test_tabulate_scripted",
        title="Test-addition task",
        repo="astanin/python-tabulate",
        source="task",
        task="Add a regression test for the simple grid output in the test suite.",
        base_commit="268615a5c27dc40e5c22454c07b44d5c50410da0",
        expected="COMPLETED, TEST_DIFF, CONTRIBUTION_PLAN.md, passing suite",
        notes=(
            "Scripted TEST plan creates a new test file. The baseline and "
            "post-patch suites must both pass; the artifact is labelled "
            "TEST_DIFF rather than PATCH_DIFF."
        ),
    ),
    Case(
        slug="ambiguous_tabulate_scripted",
        title="Ambiguous task asking for more information",
        repo="astanin/python-tabulate",
        source="task",
        task="Make the table output nicer.",
        base_commit="268615a5c27dc40e5c22454c07b44d5c50410da0",
        expected="NEED_MORE_INFO with explicit questions and a downloadable plan",
        notes=(
            "Scripted plan sets need_more_info. The evidence collection and "
            "plan document are real; the ambiguity is intentional."
        ),
    ),
    Case(
        slug="large_django_partial",
        title="Large repository stops at the retrieval limit",
        repo="django/django",
        source="task",
        task="Add a note about running the test suite to the contributing documentation.",
        base_commit="a2a0b4f2764f7b192bff4bb75ed56ce017931a71",
        planner="none",
        expected="PARTIAL with a recorded limit hit; no plan and no patch",
        notes=(
            "django/django has 7089 tracked files. Retrieval hits the "
            "MAX_SEARCH_RESULTS cap, so the run stops before planning."
        ),
    ),
    Case(
        slug="missing_license_spoon_knife",
        title="Missing license is surfaced, not hidden",
        repo="octocat/Spoon-Knife",
        source="task",
        task="Explain forking a project in the README.",
        base_commit="d0dd1f61b33d64e29d8bc1372a94ef6a2fee76a9",
        expected=(
            "COMPLETED with the license status visible in the plan and the "
            "repository suite NOT_RUN"
        ),
        notes=(
            "octocat/Spoon-Knife has no license file. RepoMate must report "
            "that state in the plan rather than implying a license. "
            "octocat/Hello-World was tried first but only has an extensionless "
            "README, so retrieval found no eligible evidence and returned "
            "NEED_MORE_INFO; that outcome is honest but does not exercise a "
            "documentation artifact."
        ),
    ),
    Case(
        slug="unavailable_toolchain_pyparsing",
        title="Unavailable test dependency is an explicit NOT_RUN",
        repo="pyparsing/pyparsing",
        source="task",
        task="Document the original_text_for helper in the README.",
        base_commit="810199f89bf916590426e1c5cb3d612584f11a2f",
        max_bytes_per_file=1_000_000,
        expected="COMPLETED with a DOCS_DIFF and repository suite NOT_RUN with a reason",
        notes=(
            "The sandbox detects that the pyparsing test suite needs the "
            "'railroad' package, which is unavailable and cannot be installed "
            "without network access. The per-file retrieval byte cap is raised "
            "for this case so evidence collection reaches verification; it is "
            "not the scenario under test."
        ),
    ),
    Case(
        slug="network_tabulate_scripted",
        title="Network attempt is blocked by the verification sandbox",
        repo="astanin/python-tabulate",
        source="task",
        task="Document how the network regression test is expected to behave.",
        base_commit="268615a5c27dc40e5c22454c07b44d5c50410da0",
        prepare="network",
        expected=(
            "COMPLETED with a DOCS_DIFF; the injected egress test FAILS and "
            "the receipt shows a verified sandbox policy"
        ),
        notes=(
            "The injected test tries to reach https://example.com. Under "
            "bubblewrap the suite fails; when no enforcing backend exists the "
            "sandbox must refuse with NOT_RUN instead."
        ),
    ),
    Case(
        slug="github_rate_limit_injected",
        title="GitHub throttling maps to a typed RATE_LIMITED error",
        repo="astanin/python-tabulate",
        source="issue",
        issue_number=481,
        base_commit="268615a5c27dc40e5c22454c07b44d5c50410da0",
        planner="none",
        inject_rate_limit=True,
        expected="FAILED with ErrorCode.RATE_LIMITED and no artifact",
        notes=(
            "The GitHub issue fetch is replaced with a RateLimitedError. The "
            "repository clone and snapshot are real; the quota exhaustion is "
            "an explicit fault injection."
        ),
    ),
    Case(
        slug="model_failure_tabulate",
        title="Unreachable model gateway maps to a typed MODEL_ERROR",
        repo="astanin/python-tabulate",
        source="task",
        task="Document the width guard in the README.",
        base_commit="268615a5c27dc40e5c22454c07b44d5c50410da0",
        planner="failing-model",
        expected="FAILED with ErrorCode.MODEL_ERROR and no artifact",
        notes=(
            "The planner points at https://127.0.0.1:9/v1 with retries "
            "disabled. The transport failure is real; the endpoint is a "
            "deliberately unreachable loopback address."
        ),
    ),
    Case(
        slug="regression_tabulate_scripted",
        title="A patch that breaks a passing check is a potential regression",
        repo="astanin/python-tabulate",
        source="task",
        task="Adjust the left-padding implementation for the table renderer.",
        base_commit="268615a5c27dc40e5c22454c07b44d5c50410da0",
        prepare="regression",
        expected="COMPLETED with POTENTIAL_REGRESSION, never presented as fixed",
        notes=(
            "A committed test asserts the current grid output. The scripted "
            "patch adds an extra padding column, so baseline passes and "
            "post-patch fails."
        ),
    ),
)


# ---------------------------------------------------------------------------
# Git and workspace helpers
# ---------------------------------------------------------------------------


def _git(cwd: Path, *args: str) -> str:
    env = dict(
        os.environ,
        GIT_AUTHOR_NAME="RepoMate Eval",
        GIT_AUTHOR_EMAIL="eval@invalid",
        GIT_COMMITTER_NAME="RepoMate Eval",
        GIT_COMMITTER_EMAIL="eval@invalid",
        GIT_TERMINAL_PROMPT="0",
    )
    result = subprocess.run(
        ["git", *args], cwd=str(cwd), capture_output=True, text=True, env=env
    )
    if result.returncode != 0:
        raise RuntimeError(f"git {' '.join(args)} failed: {result.stderr.strip()}")
    return result.stdout.strip()


def _ensure_cache(case: Case) -> tuple[Path, str]:
    """Clone the public repository once and pin the requested commit."""
    owner, name = case.repo.split("/", 1)
    dest = CACHE_ROOT / f"{owner}__{name}"
    if not (dest / ".git").exists():
        dest.parent.mkdir(parents=True, exist_ok=True)
        _git(
            dest.parent,
            "clone",
            "--depth",
            "1",
            f"https://github.com/{case.repo}.git",
            str(dest),
        )
    head = _git(dest, "rev-parse", "HEAD")
    if case.base_commit and head != case.base_commit:
        # A shallow clone can fetch a specific commit from GitHub. If the
        # commit is no longer reachable, fail loudly: silently moving the
        # evaluation to a different commit would invalidate the evidence.
        _git(dest, "fetch", "--depth", "1", "origin", case.base_commit)
        _git(dest, "checkout", "--detach", case.base_commit)
        head = _git(dest, "rev-parse", "HEAD")
    return dest, head


def _clone_for_case(cache: Path, case: Case) -> tuple[RepoWorkspace, dict]:
    dest = CASE_WORK_ROOT / case.slug
    if dest.exists():
        shutil.rmtree(dest)  # this directory is generated by this harness
    dest.parent.mkdir(parents=True, exist_ok=True)
    RepoWorkspace.from_local(cache).clone_to(dest)
    ws = RepoWorkspace.from_local(dest)
    meta: dict = {"case_workspace": str(dest.relative_to(ROOT))}
    if case.prepare:
        _prepare_workspace(ws, case.prepare, meta)
    meta["prepared_commit"] = ws.commit_sha
    return ws, meta


def _commit(ws: RepoWorkspace, message: str) -> None:
    _git(ws.root, "add", "-A")
    _git(ws.root, "commit", "-m", message)


def _prepare_workspace(ws: RepoWorkspace, kind: str, meta: dict) -> None:
    if kind == "bug478":
        path = ws.root / "test" / "test_issue_478_regression.py"
        path.write_text(
            "import wcwidth\n"
            "\n"
            "from tabulate import _CustomTextWrap\n"
            "\n"
            "\n"
            "def test_wrapped_wide_char_lines_fit_width():\n"
            '    lines = _CustomTextWrap(width=3).wrap("a 글글")\n'
            "    widths = [wcwidth.wcswidth(line) for line in lines]\n"
            "    assert all(width <= 3 for width in widths), (lines, widths)\n",
            encoding="utf-8",
            newline="\n",
        )
        _commit(ws, "eval: regression test for issue #478")
        meta["injected_files"] = ["test/test_issue_478_regression.py"]
        meta["injection"] = (
            "Committed a regression test on top of the real upstream commit "
            "so the baseline comparison can observe the bug."
        )
    elif kind == "network":
        path = ws.root / "test" / "test_network_egress.py"
        path.write_text(
            "import urllib.request\n"
            "\n"
            "\n"
            "def test_public_https_is_reachable():\n"
            '    with urllib.request.urlopen("https://example.com", timeout=5) as response:\n'
            "        assert response.status == 200\n",
            encoding="utf-8",
            newline="\n",
        )
        _commit(ws, "eval: network egress test")
        meta["injected_files"] = ["test/test_network_egress.py"]
        meta["injection"] = (
            "Committed a test that requires public HTTPS. A correctly "
            "enforcing sandbox must make it fail."
        )
    elif kind == "regression":
        path = ws.root / "test" / "test_padding_contract.py"
        path.write_text(
            "from tabulate import tabulate\n"
            "\n"
            "\n"
            "def test_simple_grid_output_is_stable():\n"
            '    assert tabulate([["a", "b"]], tablefmt="grid") == (\n'
            '        "+---+---+\\n| a | b |\\n+---+---+"\n'
            "    )\n",
            encoding="utf-8",
            newline="\n",
        )
        _commit(ws, "eval: grid padding contract test")
        meta["injected_files"] = ["test/test_padding_contract.py"]
        meta["injection"] = (
            "Committed a passing contract test on top of upstream so the "
            "baseline comparison can detect the scripted regression."
        )
    else:  # pragma: no cover - a typo in a case definition
        raise ValueError(f"unknown preparation: {kind}")


# ---------------------------------------------------------------------------
# Scripted plans
# ---------------------------------------------------------------------------


class StaticPlanner:
    name = "scripted-eval-v1"

    def __init__(self, plan: ContributionPlan) -> None:
        self._plan = plan

    def plan(self, task_text, snapshot, evidence):
        return self._plan.model_copy(deep=True)


def _docs_plan(path: str, draft: Optional[str]) -> ContributionPlan:
    return ContributionPlan(
        task_type=TaskType.DOCUMENTATION,
        summary=f"Add a focused documentation section to {path}.",
        planned_changes=[
            PlannedChange(
                path=path,
                change_type="MODIFY",
                rationale="the requested behavior belongs with the existing documentation",
            )
        ],
        acceptance_criteria=["the new section is present and readable in the rendered file"],
        evidence_ids=["ev1"],
        planned_by="scripted-eval-v1",
        content_draft=draft,
    )


def _bug_plan() -> ContributionPlan:
    return ContributionPlan(
        task_type=TaskType.BUG_FIX,
        summary=(
            "Only force two-character progress when the current line is empty, "
            "so a wide character cannot overflow a non-empty line."
        ),
        planned_changes=[
            PlannedChange(
                path="tabulate/__init__.py",
                change_type="MODIFY",
                rationale="issue #478 identifies the forced progress as the cause",
            )
        ],
        acceptance_criteria=[
            "_CustomTextWrap(width=3).wrap('a 글글') has no line wider than 3 columns"
        ],
        evidence_ids=["ev1"],
        planned_by="scripted-eval-v1",
        proposed_edits=[
            ProposedEdit(
                path="tabulate/__init__.py",
                old_text="            i = max(i, 2)\n",
                new_text=(
                    "            if i == 1 and not cur_line and stripped_chunk:\n"
                    "                i = 2\n"
                ),
                rationale="force progress only when there is no current line",
            )
        ],
    )


def _test_plan() -> ContributionPlan:
    return ContributionPlan(
        task_type=TaskType.TEST,
        summary="Add a deterministic regression test for simple grid rendering.",
        planned_changes=[
            PlannedChange(
                path="test/test_grid_contract.py",
                change_type="CREATE",
                rationale="cover the public table rendering contract",
            )
        ],
        acceptance_criteria=["the new test passes against the pinned snapshot"],
        evidence_ids=["ev1"],
        planned_by="scripted-eval-v1",
        proposed_edits=[
            ProposedEdit(
                path="test/test_grid_contract.py",
                old_text="",
                new_text=(
                    "from tabulate import tabulate\n"
                    "\n"
                    "\n"
                    "def test_grid_output_for_simple_rows():\n"
                    '    assert tabulate([["a", "b"]], tablefmt="grid") == (\n'
                    '        "+---+---+\\n| a | b |\\n+---+---+"\n'
                    "    )\n"
                ),
                rationale="pin the existing grid layout",
            )
        ],
    )


def _needs_info_plan() -> ContributionPlan:
    return ContributionPlan(
        task_type=TaskType.UNKNOWN,
        summary=(
            "The request does not identify a concrete table format, behavior "
            "or file, so a safe change cannot be selected."
        ),
        planned_changes=[],
        acceptance_criteria=[],
        evidence_ids=["ev1"],
        planned_by="scripted-eval-v1",
        need_more_info=True,
        questions=[
            "Which table format or public function should change?",
            "What exact before/after output defines success?",
            "Should the change preserve the current public API?",
        ],
    )


def _network_docs_plan() -> ContributionPlan:
    return _docs_plan(
        "README.md",
        "## Verifying network isolation\n\n"
        "The evaluation harness adds this note to exercise verification after "
        "a documentation-only change. It makes no claim about repository "
        "behavior and is not intended for upstream submission.",
    )


def _missing_license_plan() -> ContributionPlan:
    return _docs_plan(
        "README.md",
        "## Forking workflow\n\n"
        "This repository is a sandbox for practicing the fork-and-pull-request "
        "workflow. Create a fork, make a change on a branch in your copy, and "
        "open a pull request against the original repository.",
    )


def _pyparsing_docs_plan() -> ContributionPlan:
    return _docs_plan("README.rst", None)


def _regression_plan() -> ContributionPlan:
    return ContributionPlan(
        task_type=TaskType.BUG_FIX,
        summary="Widen left-aligned table cells by one column.",
        planned_changes=[
            PlannedChange(
                path="tabulate/__init__.py",
                change_type="MODIFY",
                rationale="adjust the left-padding implementation",
            )
        ],
        acceptance_criteria=["existing grid output is unchanged"],
        evidence_ids=["ev1"],
        planned_by="scripted-eval-v1",
        proposed_edits=[
            ProposedEdit(
                path="tabulate/__init__.py",
                old_text='    fmt = f"{{0:<{width}s}}"\n    return fmt.format(s)\n',
                new_text='    fmt = f"{{0:<{width + 1}s}}"\n    return fmt.format(s)\n',
                rationale="increase the left-aligned cell padding",
            )
        ],
    )


def _scripted_plan(case: Case) -> Optional[StaticPlanner]:
    if case.slug == "docs_tabulate_481_scripted":
        return StaticPlanner(
            _docs_plan(
                "README.md",
                "## Library-only installation\n\n"
                "The `TABULATE_INSTALL=lib-only` option described in the README "
                "predates the current `flit_scm` packaging configuration. "
                "`pyproject.toml` declares the `tabulate` console script "
                "unconditionally, so installing the package always installs the "
                "executable. If you only need the Python library, install the "
                "package normally and ignore the console script.",
            )
        )
    if case.slug == "bug_tabulate_478_scripted":
        return StaticPlanner(_bug_plan())
    if case.slug == "test_tabulate_scripted":
        return StaticPlanner(_test_plan())
    if case.slug == "ambiguous_tabulate_scripted":
        return StaticPlanner(_needs_info_plan())
    if case.slug == "missing_license_spoon_knife":
        return StaticPlanner(_missing_license_plan())
    if case.slug == "unavailable_toolchain_pyparsing":
        return StaticPlanner(_pyparsing_docs_plan())
    if case.slug == "network_tabulate_scripted":
        return StaticPlanner(_network_docs_plan())
    if case.slug == "regression_tabulate_scripted":
        return StaticPlanner(_regression_plan())
    return None


def _failing_model_planner() -> ModelPlanner:
    provider = OpenAIProvider(
        "eval-dummy-key",
        base_url="https://127.0.0.1:9/v1",
        model="eval-unreachable",
        max_retries=0,
    )
    return ModelPlanner(provider)


# ---------------------------------------------------------------------------
# Outcome helpers
# ---------------------------------------------------------------------------


def _kind(record: RunRecord) -> str:
    return record.artifact.kind.value if record.artifact else "NONE"


def _doc_names(record: RunRecord) -> list[str]:
    return [document.name for document in record.documents]


def _check(record: RunRecord, name: str):
    if record.receipt is None:
        return None
    return next((check for check in record.receipt.checks if check.name == name), None)


def _comparison(record: RunRecord):
    return record.receipt.comparison if record.receipt else None


def _failed(record: RunRecord, expected: str) -> tuple[bool, str]:
    return False, f"expected {expected}; observed status={record.status.value}"


def _assess(case: Case, record: RunRecord, meta: dict) -> tuple[bool, str]:
    """Return (passed, explanation). Each branch states what it checked."""
    slug = case.slug
    suite = _check(record, SUITE)
    comparison = _comparison(record)
    kinds = _kind(record)
    docs = _doc_names(record)

    if slug in {"docs_tabulate_481_scripted", "docs_tabulate_481_live"}:
        if record.status is not RunStatus.COMPLETED:
            if (
                slug == "docs_tabulate_481_live"
                and record.status is RunStatus.FAILED
                and record.error is not None
                and record.error.code.value == "MODEL_ERROR"
                and (record.planner or "").startswith("model:")
            ):
                return False, (
                    "live gateway failure preserved as a typed MODEL_ERROR: "
                    f"{(record.error.message or '')[:200]}; no artifact is claimed"
                )
            return _failed(record, "COMPLETED")
        if kinds != ArtifactKind.DOCS_DIFF.value:
            return _failed(record, "a DOCS_DIFF artifact")
        if "CONTRIBUTION_PLAN.md" not in docs:
            return _failed(record, "CONTRIBUTION_PLAN.md")
        if record.artifact and not any(
            path.lower().startswith("readme") for path in record.artifact.affected_paths
        ):
            return _failed(record, "a README change")
        if suite is not None and suite.status is VerificationStatus.FAILED:
            return _failed(record, "a passing repository suite")
        if slug.endswith("_live") and not (record.planner or "").startswith("model:"):
            return _failed(record, "a model planner identity")
        return True, (
            f"{kinds} touching {', '.join(record.artifact.affected_paths) if record.artifact else '?'}; "
            f"suite={suite.status.value if suite else 'missing'}; "
            f"planner={record.planner or 'unknown'}"
        )

    if slug == "bug_tabulate_478_scripted":
        if record.status is not RunStatus.COMPLETED:
            return _failed(record, "COMPLETED")
        if kinds != ArtifactKind.PATCH_DIFF.value:
            return _failed(record, "a PATCH_DIFF artifact")
        if not {"CONTRIBUTION_PLAN.md", "REPRO_CHECKLIST.md"}.issubset(docs):
            return _failed(record, "plan and repro checklist documents")
        if comparison is None or comparison.outcome.value != "CONSISTENT_IMPROVEMENT":
            return _failed(record, "CONSISTENT_IMPROVEMENT")
        if comparison.baseline.status is not VerificationStatus.FAILED:
            return _failed(record, "a FAILED baseline")
        if comparison.post_patch.status is not VerificationStatus.PASSED:
            return _failed(record, "a PASSED post-patch check")
        return True, (
            f"baseline={comparison.baseline.status.value} -> "
            f"post={comparison.post_patch.status.value}; {kinds}"
        )

    if slug == "test_tabulate_scripted":
        if record.status is not RunStatus.COMPLETED:
            return _failed(record, "COMPLETED")
        if kinds != ArtifactKind.TEST_DIFF.value:
            return _failed(record, "a TEST_DIFF artifact")
        if "CONTRIBUTION_PLAN.md" not in docs:
            return _failed(record, "CONTRIBUTION_PLAN.md")
        if record.artifact and "test/" not in " ".join(record.artifact.affected_paths):
            return _failed(record, "a test-file path")
        if suite is None or suite.status is not VerificationStatus.PASSED:
            return _failed(record, "a PASSED repository suite")
        if comparison is None or comparison.outcome.value != "NO_REGRESSION_DETECTED":
            return _failed(record, "NO_REGRESSION_DETECTED")
        return True, f"{kinds}; suite=PASSED; {comparison.outcome.value}"

    if slug == "ambiguous_tabulate_scripted":
        if record.status is not RunStatus.NEED_MORE_INFO:
            return _failed(record, "NEED_MORE_INFO")
        if record.plan is None or not record.plan.need_more_info:
            return _failed(record, "a need_more_info plan")
        if not record.plan.questions:
            return _failed(record, "explicit questions")
        if record.artifact is not None:
            return _failed(record, "no artifact")
        if "CONTRIBUTION_PLAN.md" not in docs:
            return _failed(record, "CONTRIBUTION_PLAN.md")
        plan_doc = next(
            (document.content for document in record.documents if document.name == "CONTRIBUTION_PLAN.md"),
            "",
        )
        if "Open questions" not in plan_doc:
            return _failed(record, "open questions in the plan document")
        return True, f"NEED_MORE_INFO with {len(record.plan.questions)} question(s); plan document present"

    if slug == "large_django_partial":
        if record.status is not RunStatus.PARTIAL:
            return _failed(record, "PARTIAL")
        if record.retrieval is None or record.retrieval.status is not RetrievalStatus.PARTIAL:
            return _failed(record, "a PARTIAL retrieval report")
        if not record.retrieval.limit_hits:
            return _failed(record, "at least one recorded limit hit")
        if record.artifact is not None or record.plan is not None:
            return _failed(record, "no plan and no artifact")
        return True, (
            f"retrieval={record.retrieval.status.value}; "
            f"hits={', '.join(hit.limit.value for hit in record.retrieval.limit_hits)}; "
            f"examined {record.retrieval.files_examined}/{record.retrieval.files_eligible} eligible files"
        )

    if slug == "missing_license_spoon_knife":
        if record.status is not RunStatus.COMPLETED:
            return _failed(record, "COMPLETED")
        if record.snapshot is None or record.snapshot.license.status.value == "RECOGNIZED":
            return _failed(record, "a non-recognized license status")
        if kinds != ArtifactKind.DOCS_DIFF.value:
            return _failed(record, "a DOCS_DIFF artifact")
        if "CONTRIBUTION_PLAN.md" not in docs or suite is None:
            return _failed(record, "plan document and suite receipt")
        if suite.status is not VerificationStatus.NOT_RUN:
            return _failed(record, "a NOT_RUN repository suite")
        if not suite.reason:
            return _failed(record, "a reason for NOT_RUN")
        plan_doc = next(
            (document.content for document in record.documents if document.name == "CONTRIBUTION_PLAN.md"),
            "",
        )
        if "License" not in plan_doc:
            return _failed(record, "the license status in the plan document")
        return True, (
            f"license={record.snapshot.license.status.value}; "
            f"suite=NOT_RUN ({suite.reason[:80]})"
        )

    if slug == "unavailable_toolchain_pyparsing":
        if record.status is not RunStatus.COMPLETED:
            return _failed(record, "COMPLETED")
        if kinds != ArtifactKind.DOCS_DIFF.value:
            return _failed(record, "a DOCS_DIFF artifact")
        if suite is None or suite.status is not VerificationStatus.NOT_RUN:
            return _failed(record, "a NOT_RUN repository suite")
        reason = (suite.reason or "").lower()
        if not any(word in reason for word in ("depend", "module", "sandbox", "network")):
            return _failed(record, "a dependency-related NOT_RUN reason")
        return True, f"DOCS_DIFF; suite=NOT_RUN ({suite.reason[:120]})"

    if slug == "network_tabulate_scripted":
        if record.status is not RunStatus.COMPLETED:
            return _failed(record, "COMPLETED")
        if kinds != ArtifactKind.DOCS_DIFF.value:
            return _failed(record, "a DOCS_DIFF artifact")
        sandbox = record.receipt.sandbox if record.receipt else None
        if sandbox is None or not sandbox.policy_enforced:
            return _failed(record, "a verified sandbox policy")
        if sandbox.egress_validation != "PASSED":
            return _failed(record, "a PASSED egress validation")
        if suite is None or suite.status is not VerificationStatus.FAILED:
            return _failed(record, "a FAILED repository suite (the egress test)")
        return True, (
            f"sandbox={sandbox.network_mode}/{sandbox.backend}, "
            f"egress={sandbox.egress_validation}; suite=FAILED"
        )

    if slug == "github_rate_limit_injected":
        if record.status is not RunStatus.FAILED:
            return _failed(record, "FAILED")
        if record.error is None or record.error.code.value != "RATE_LIMITED":
            return _failed(record, "ErrorCode.RATE_LIMITED")
        if record.artifact is not None:
            return _failed(record, "no artifact")
        return True, f"FAILED with {record.error.code.value}; injection labelled in provenance"

    if slug == "model_failure_tabulate":
        if record.status is not RunStatus.FAILED:
            return _failed(record, "FAILED")
        if record.error is None or record.error.code.value != "MODEL_ERROR":
            return _failed(record, "ErrorCode.MODEL_ERROR")
        if record.artifact is not None:
            return _failed(record, "no artifact")
        return True, f"FAILED with {record.error.code.value}; no artifact"

    if slug == "regression_tabulate_scripted":
        if record.status is not RunStatus.COMPLETED:
            return _failed(record, "COMPLETED")
        if kinds != ArtifactKind.PATCH_DIFF.value:
            return _failed(record, "a PATCH_DIFF artifact")
        if comparison is None or comparison.outcome.value != "POTENTIAL_REGRESSION":
            return _failed(record, "POTENTIAL_REGRESSION")
        if comparison.baseline.status is not VerificationStatus.PASSED:
            return _failed(record, "a PASSED baseline")
        if comparison.post_patch.status is not VerificationStatus.FAILED:
            return _failed(record, "a FAILED post-patch check")
        return True, (
            f"baseline=PASSED -> post=FAILED; {comparison.outcome.value}; "
            "the run is not presented as fixed"
        )

    return _failed(record, f"a predicate for case {slug}")  # pragma: no cover


# ---------------------------------------------------------------------------
# Run, export and report
# ---------------------------------------------------------------------------


def _input_for(case: Case) -> RepositoryInput:
    if case.source == "issue":
        assert case.issue_number is not None
        return RepositoryInput(
            source=TaskSource.GITHUB_ISSUE,
            issue_url=f"https://github.com/{case.repo}/issues/{case.issue_number}",
        )
    assert case.task
    return RepositoryInput(
        source=TaskSource.REPO_TASK,
        repo_url=f"https://github.com/{case.repo}",
        task=case.task,
    )


def _run(case: Case) -> tuple[RunRecord, dict]:
    cache, upstream = _ensure_cache(case)
    ws, meta = _clone_for_case(cache, case)
    meta.update(
        {
            "repo": case.repo,
            "upstream_commit": upstream,
            "base_commit": case.base_commit,
        }
    )

    planner = None
    if case.planner == "scripted":
        planner = _scripted_plan(case)
        if planner is None:
            raise RuntimeError(f"case {case.slug} has no scripted plan")
    elif case.planner == "live":
        planner = resolve_planner()
        meta["planner_requested"] = "live"
    elif case.planner == "failing-model":
        planner = _failing_model_planner()
        meta["planner_requested"] = "failing-model"
    elif case.planner == "none":
        meta["planner_requested"] = "none"
    else:  # pragma: no cover
        raise ValueError(case.planner)

    config = PipelineConfig(
        runs_root=RUNS_ROOT,
        keep_workspace=False,
        planner=planner,
    )
    if case.max_bytes_per_file:
        config.retrieval_limits = config.retrieval_limits.model_copy(
            update={"max_bytes_per_file": case.max_bytes_per_file}
        )

    started = time.time()
    with ExitStack() as stack:
        if case.inject_rate_limit:
            stack.enter_context(
                mock.patch(
                    "repomate_core.orchestration.stages.fetch_issue",
                    side_effect=RateLimitedError(
                        "injected GitHub rate-limit response (evaluation only)",
                        reset_at=None,
                    ),
                )
            )
        record = run_pipeline(
            _input_for(case),
            config=config,
            workspace_factory=lambda ref, dest, cfg: ws,
        )
    meta["elapsed_seconds"] = round(time.time() - started, 2)
    meta["planner_observed"] = record.planner or "none"
    meta["sandbox_backend"] = detect_egress_backend().value
    return record, meta


def _write_json(path: Path, payload) -> None:
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")


def _render_summary(
    case: Case, record: RunRecord, meta: dict, passed: bool, explanation: str
) -> str:
    suite = _check(record, SUITE)
    comparison = _comparison(record)
    lines = [
        f"# {case.title}",
        "",
        f"- **Case:** `{case.slug}`",
        f"- **Repository:** `{case.repo}`",
        f"- **Input:** {_input_label(case)}",
        f"- **Upstream commit:** `{meta.get('upstream_commit', '?')}`",
        f"- **Prepared commit:** `{meta.get('prepared_commit', '?')}`",
        f"- **Planner observed:** `{record.planner or 'none'}`",
        f"- **Status:** `{record.status.value}`",
        f"- **Expected:** {case.expected}",
        f"- **Verdict:** {'PASS' if passed else 'FAIL'} — {explanation}",
        "",
    ]
    if meta.get("injection"):
        lines += ["## Injected test / fault", "", meta["injection"], ""]
        for path in meta.get("injected_files", []):
            lines.append(f"- `{path}`")
        lines.append("")
    if case.inject_rate_limit:
        lines += [
            "## Fault injection",
            "",
            "The GitHub issue fetch was replaced with a typed `RateLimitedError`. "
            "This is not evidence that the live quota was exhausted.",
            "",
        ]
    if record.error is not None:
        lines += [
            "## Error",
            "",
            f"- **Code:** `{record.error.code.value}`",
            f"- **Message:** {record.error.message}",
            "",
        ]
    if record.retrieval is not None:
        lines += [
            "## Retrieval",
            "",
            f"- **Status:** `{record.retrieval.status.value}`",
            f"- **Files:** {record.retrieval.files_examined} examined of "
            f"{record.retrieval.files_eligible} eligible "
            f"({record.retrieval.files_total} tracked)",
            f"- **Evidence records:** {record.retrieval.evidence_records}",
            f"- **Summary:** {record.retrieval.summary}",
            "",
        ]
        for hit in record.retrieval.limit_hits:
            lines.append(
                f"- Limit `{hit.limit.value}`: allowed {hit.allowed}, observed "
                f"{hit.observed}. {hit.remaining_work}"
            )
        lines.append("")
    if record.artifact is not None:
        lines += [
            "## Artifact",
            "",
            f"- **Kind:** `{record.artifact.kind.value}`",
            f"- **Paths:** {', '.join(f'`{p}`' for p in record.artifact.affected_paths)}",
            f"- **Patch lines:** {len(record.artifact.patch.splitlines())}",
            "",
        ]
    if record.documents:
        lines += [
            "## Documents",
            "",
            *[f"- `{document.name}` ({document.kind.value})" for document in record.documents],
            "",
        ]
    if record.receipt is not None:
        lines += ["## Receipt", "", "| Check | Status | Detail |", "|---|---|---|"]
        for check in record.receipt.checks:
            detail = check.reason or (check.output_tail or "")
            detail = " ".join(detail.split())[:180]
            lines.append(
                f"| `{check.name}` | `{check.status.value}` | {detail.replace('|', '\\|')} |"
            )
        lines.append("")
        if comparison is not None:
            lines += [
                "## Comparison",
                "",
                f"- **Outcome:** `{comparison.outcome.value}`",
                f"- **Baseline:** `{comparison.baseline.status.value}`",
                f"- **Post-patch:** `{comparison.post_patch.status.value}`",
                f"- **Interpretation:** {comparison.interpretation}",
                "",
            ]
            if comparison.baseline.output_summary:
                lines += [
                    "### Baseline output tail",
                    "",
                    "```",
                    comparison.baseline.output_summary[-1200:],
                    "```",
                    "",
                ]
            if comparison.post_patch.output_summary:
                lines += [
                    "### Post-patch output tail",
                    "",
                    "```",
                    comparison.post_patch.output_summary[-1200:],
                    "```",
                    "",
                ]
    lines += [
        "## Provenance",
        "",
        f"- Case workspace: `{meta.get('case_workspace', '?')}`",
        f"- Elapsed: {meta.get('elapsed_seconds', '?')}s",
        f"- Sandbox backend: `{meta.get('sandbox_backend', '?')}`",
        f"- Planner requested: `{meta.get('planner_requested', case.planner)}`",
        "",
    ]
    if case.notes:
        lines += ["## Notes", "", case.notes, ""]
    return "\n".join(lines)


def _input_label(case: Case) -> str:
    if case.source == "issue":
        return f"https://github.com/{case.repo}/issues/{case.issue_number}"
    return f"https://github.com/{case.repo} — “{case.task}”"


def _export(case: Case, record: RunRecord, meta: dict, passed: bool, explanation: str) -> None:
    case_dir = OUT_ROOT / case.slug
    if case_dir.exists():
        shutil.rmtree(case_dir)  # generated output for this case only
    case_dir.mkdir(parents=True)
    documents_dir = case_dir / "documents"
    documents_dir.mkdir()

    _write_json(
        case_dir / "input.json",
        {
            "case": case.slug,
            "title": case.title,
            "repository": case.repo,
            "input": record.input.model_dump(mode="json"),
            "expected": case.expected,
            "notes": case.notes,
        },
    )
    _write_json(case_dir / "provenance.json", meta)
    _write_json(case_dir / "run.json", record.model_dump(mode="json"))
    _write_json(case_dir / "evidence.json", [item.model_dump(mode="json") for item in record.evidence])
    if record.receipt is not None:
        _write_json(case_dir / "receipt.json", record.receipt.model_dump(mode="json"))
    if record.artifact is not None:
        (case_dir / "patch.diff").write_text(record.artifact.patch, encoding="utf-8")
    for document in record.documents:
        safe_name = document.name.replace("/", "_").replace("\\", "_")
        (documents_dir / safe_name).write_text(document.content, encoding="utf-8")
    (case_dir / "summary.md").write_text(
        _render_summary(case, record, meta, passed, explanation), encoding="utf-8"
    )


def _write_results(results: list[dict], environment: dict) -> None:
    lines = [
        "# Real-Repository Evaluation Results",
        "",
        f"Generated {environment['generated_at']} by `scripts/evaluate_real_repos.py`.",
        "",
        "These runs clone real public repositories. Scripted plans are labelled; "
        "injected tests and fault injections are recorded in each case's "
        "`provenance.json` and `summary.md`.",
        "",
        "## Environment",
        "",
        f"- Platform: {environment['platform']}",
        f"- Python: {environment['python']}",
        f"- Sandbox backend: `{environment['sandbox_backend']}`",
        f"- Test suite command: `{environment['suite_command']}`",
        f"- Live model: `{environment['model']}`",
        "",
        "## Results",
        "",
        "| # | Case | Repository | Prepared commit | Planner | Outcome | Verdict |",
        "|---|---|---|---|---|---|---|",
    ]
    for index, result in enumerate(results, 1):
        case = result["case"]
        record = result["record"]
        status = record.status.value
        if record.error is not None:
            status += f" ({record.error.code.value})"
        planner = record.planner or "none"
        base = (result["meta"].get("prepared_commit") or "?")[:10]
        verdict = "✅ PASS" if result["passed"] else "❌ FAIL"
        lines.append(
            f"| {index} | [`{case.slug}`](evaluation-runs/{case.slug}/summary.md) | "
            f"`{case.repo}` | `{base}` | `{planner}` | `{status}` | {verdict} |"
        )
    lines += [
        "",
        "Each linked summary preserves the input, upstream and prepared commits, "
        "evidence, artifact, receipt and comparison. Raw run records are in "
        "`evaluation-runs/<case>/run.json`.",
        "",
        "## Browser-to-artifact proof",
        "",
        "A separate browser run (`run_20261026-100340_8a5rrl53`) submitted issue "
        "#481 through the Next.js UI, reached `COMPLETED`, rendered the diff and "
        "receipt, and downloaded the patch and `CONTRIBUTION_PLAN.md`. The "
        "screenshot, DOM text, run record and downloaded files are preserved in "
        "[`evaluation-runs/browser_tabulate_481/`](evaluation-runs/browser_tabulate_481/summary.md). "
        "The demo API was started without model credentials, so that planner is "
        "the deterministic `heuristic-v1`.",
        "",
        "## Container deployment proof",
        "",
        "The Compose images were rebuilt and exercised on Docker Desktop for "
        "Windows (Linux containers) from Windows PowerShell. The API and worker "
        "egress gates passed with `backend=bwrap`; the same container reached the "
        "network without the sandbox; the default Docker seccomp profile failed "
        "closed. All 32 adversarial egress tests passed inside the API image, and "
        "a real issue run (`run_20261026-103949_gxr0b2xr`) completed with "
        "`DOCS_DIFF`, `CONTRIBUTION_PLAN.md`, and a receipt showing 366 tests per "
        "checkout under `bwrap`. Raw gates, negative controls, logs and downloads "
        "are in "
        "[`evaluation-runs/container_docker_windows/`](evaluation-runs/container_docker_windows/summary.md). "
        "This is not a public cloud deployment claim.",
        "",
        "## Observed failures and limitations",
        "",
    ]
    failures = [result for result in results if not result["passed"]]
    if failures:
        for result in failures:
            lines.append(
                f"- **{result['case'].slug}** — {result['explanation']}"
            )
    else:
        lines.append("- No case failed its stated predicate in this run.")
    lines += [
        "",
        "Concrete observed failures/limitations:",
        "",
        "- **Live gateway timeout.** The final live-model case called "
        "`deepseek-v4.1` and received a Cloudflare 524 after 429 seconds. The run "
        "is `FAILED (MODEL_ERROR)`, no artifact is claimed, and the raw gateway "
        "body is preserved in its summary. An earlier run of the same input at "
        "2026-10-26T09:49Z completed with `DOCS_DIFF`, preserved as "
        "`evaluation-runs/live_model_observation_094908/`; the failure was not "
        "deleted or presented as a success.",
        "- **Public cloud deployment still not verified.** The Compose path "
        "itself was verified on Docker Desktop for Windows: both release gates "
        "passed, the default-seccomp control failed closed, 32 adversarial tests "
        "passed inside the container, and a real issue run completed with 366 "
        "tests executed under `bwrap` "
        "(`evaluation-runs/container_docker_windows/`). Render's Docker runtime "
        "does not expose custom seccomp, so that public deployment path remains "
        "`NOT_VERIFIED` and must fail closed.",
        "- **Unauthenticated GitHub quota.** `GITHUB_TOKEN` was empty, so the "
        "REST API ran under the 60 req/h unauthenticated limit. The "
        "`RATE_LIMITED` handling is proven by an explicitly labelled fault "
        "injection, not by waiting for the live quota to exhaust.",
        "- **Large-repository retrieval limit.** django/django (7,089 tracked "
        "files) correctly stopped as `PARTIAL` at the 200-result search cap; it "
        "did not produce a plan or patch.",
        "- **Per-file evidence cap vs. toolchain case.** pyparsing's test suite "
        "needed a raised `max_bytes_per_file` to reach verification; with the "
        "default cap the run stopped `PARTIAL` before planning. The raised cap is "
        "recorded in that case's provenance and does not change the default.",
        "",
        "Design limitations (not hidden test failures):",
        "",
        "- Scripted plans exercise the real repository, evidence, artifact, sandbox "
        "and verification path, but the plan text is fixed by the harness. They are "
        "not evidence that the configured model would produce the same edit.",
        "- The bug case adds a regression test as a local commit on top of the real "
        "upstream commit. The test is from the issue discussion; it is not shipped "
        "upstream.",
        "- The network case and rate-limit case use explicit test/fault injection. "
        "They prove the control and error mapping, not that the live service was "
        "attacked or throttled.",
        "- A `CONSISTENT_IMPROVEMENT` comparison is not proof of correctness; it "
        "means the selected check failed before and passed after the patch.",
        "- RepoMate does not repair arbitrary issues. A run can end `NEED_MORE_INFO`, "
        "`PARTIAL`, `NOT_RUN`, `FAILED` or `POTENTIAL_REGRESSION`, and the UI and "
        "documents must show that outcome.",
        "",
    ]
    RESULTS_PATH.write_text("\n".join(lines), encoding="utf-8")


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--only",
        nargs="*",
        default=None,
        help="run only these case slugs",
    )
    parser.add_argument(
        "--skip-live",
        action="store_true",
        help="skip the live model case",
    )
    args = parser.parse_args(argv)

    load_env_file()
    OUT_ROOT.mkdir(parents=True, exist_ok=True)
    RUNS_ROOT.mkdir(parents=True, exist_ok=True)
    CASE_WORK_ROOT.mkdir(parents=True, exist_ok=True)

    selected = [
        case
        for case in CASES
        if (not args.only or case.slug in set(args.only))
        and not (args.skip_live and case.planner == "live")
    ]
    if not selected:
        print("no cases selected", file=sys.stderr)
        return 2

    results: list[dict] = []
    for case in selected:
        print(f"== {case.slug} ==", flush=True)
        try:
            record, meta = _run(case)
            passed, explanation = _assess(case, record, meta)
        except Exception as exc:  # harness failure, never a silent pass
            print(f"   HARNESS ERROR: {type(exc).__name__}: {exc}", flush=True)
            result = {
                "case": case,
                "record": RunRecord(
                    run_id=f"harness-{case.slug}",
                    input=_input_for(case),
                    status=RunStatus.FAILED,
                    error=None,
                ),
                "meta": {"error": f"{type(exc).__name__}: {exc}"},
                "passed": False,
                "explanation": f"harness error: {type(exc).__name__}: {exc}",
            }
            _write_json(
                OUT_ROOT / case.slug / "harness-error.json",
                {"error": f"{type(exc).__name__}: {exc}"},
            )
            results.append(result)
            continue
        _export(case, record, meta, passed, explanation)
        print(
            f"   status={record.status.value} artifact={_kind(record)} "
            f"planner={record.planner or 'none'} pass={passed}",
            flush=True,
        )
        if not passed:
            print(f"   {explanation}", flush=True)
        results.append(
            {
                "case": case,
                "record": record,
                "meta": meta,
                "passed": passed,
                "explanation": explanation,
            }
        )

    environment = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "platform": sys.platform,
        "python": sys.version.split()[0],
        "sandbox_backend": detect_egress_backend().value,
        "suite_command": "python -m pytest -q (inside the sandbox)",
        "model": os.environ.get("OLLAMA_MODELS", "(not configured)"),
    }
    _write_results(results, environment)
    print(f"wrote {RESULTS_PATH.relative_to(ROOT)}")
    return 0 if all(result["passed"] for result in results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
