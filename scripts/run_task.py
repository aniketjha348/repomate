"""Developer/evaluation utility: run one RepoMate task end-to-end.

This is a demo harness for PS04 evaluation, not a product CLI — the
product surface is the web app and HTTP API.

Usage:

    python scripts/run_task.py --repo https://github.com/owner/repo \
        --task "Add documentation for X to the README"

    python scripts/run_task.py --issue https://github.com/owner/repo/issues/12
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "packages"))

from repomate_core.contracts import RepositoryInput, RunStatus, TaskSource
from repomate_core.orchestration.pipeline import PipelineConfig, resolve_planner, run_pipeline
from repomate_core.orchestration.store import RunStore


def main() -> int:
    parser = argparse.ArgumentParser(description="Run one RepoMate contribution task")
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--issue", help="GitHub issue URL")
    source.add_argument("--repo", help="GitHub repository URL")
    parser.add_argument("--task", help="Development task text (required with --repo)")
    parser.add_argument("--runs-root", default="var/runs", help="Directory for run records")
    parser.add_argument("--keep-workspace", action="store_true")
    args = parser.parse_args()

    if args.repo and not (args.task and args.task.strip()):
        parser.error("--repo requires --task")

    if args.issue:
        run_input = RepositoryInput(source=TaskSource.GITHUB_ISSUE, issue_url=args.issue)
    else:
        run_input = RepositoryInput(
            source=TaskSource.REPO_TASK, repo_url=args.repo, task=args.task
        )

    config = PipelineConfig(
        runs_root=Path(args.runs_root),
        keep_workspace=args.keep_workspace,
    )

    print(f"planner: {resolve_planner().name}")
    print(f"runs root: {config.runs_root}\n")

    record = run_pipeline(
        run_input,
        config=config,
        event_cb=lambda e: print(f"  [{e.status:>9}] {e.stage.value if e.stage else '-':<18} {e.message}"),
    )

    print(f"\nstatus: {record.status.value}")
    if record.snapshot:
        snap = record.snapshot
        lic = snap.license
        print(
            f"snapshot: {snap.owner}/{snap.name}@{snap.commit_sha[:10]} "
            f"(branch {snap.default_branch}, license {lic.status.value}"
            + (f": {lic.spdx_id}" if lic.spdx_id else "") + ")"
        )
    if record.plan:
        print(f"plan: {record.plan.summary}")
        for question in record.plan.questions:
            print(f"  question: {question}")
    if record.error:
        print(f"error: {record.error.code.value}: {record.error.message}")
    if record.receipt:
        print(f"verification overall: {record.receipt.overall.value}")
        for check in record.receipt.checks:
            suffix = f" — {check.reason}" if check.status.value == "NOT_RUN" else ""
            print(f"  {check.status.value:>7}  {check.name} ({check.command or 'no command'}){suffix}")
    if record.artifact:
        store = RunStore(config.runs_root)
        path = store.artifact_path(record.run_id)
        print(f"\npatch ({len(record.artifact.patch.splitlines())} lines): {path}")
        print("----- patch.diff -----")
        print(record.artifact.patch)
        print("---------------------")
    print(f"run record: {config.runs_root / record.run_id / 'run.json'}")

    desired = {RunStatus.COMPLETED, RunStatus.NEED_MORE_INFO}
    return 0 if record.status in desired else 1


if __name__ == "__main__":
    raise SystemExit(main())
