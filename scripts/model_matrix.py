"""Model matrix evaluation: run one real open issue through every
OpenAI-compatible gateway model and record outcomes in docs/model-matrix.md.

Usage (env from .env):
    set -a; source .env; set +a
    python scripts/model_matrix.py --issue https://github.com/psf/black/issues/2365
"""

from __future__ import annotations

import argparse
import shutil
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "packages"))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from repomate_core.contracts import RepositoryInput, RunStatus, TaskSource
from repomate_core.models import OpenAIProvider
from repomate_core.orchestration.pipeline import run_pipeline
from repomate_core.orchestration.pipeline_config import PipelineConfig
from repomate_core.planning.model_planner import ModelPlanner
from repomate_core.repository.workspace import RepoWorkspace
from repomate_core.safety.url_guard import parse_github_url

MODELS = [
    "deepseek-v4.1",
    "deepseek-v4-flash",
    "glm-5.3-flash",
    "beam-1.0",
    "nemotron-3.5-super-vl",
]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--issue", required=True)
    parser.add_argument("--out", default="docs/model-matrix.md")
    args = parser.parse_args()

    import os

    api_key = os.environ.get("OPENAI_API_KEY") or os.environ.get("VYCE_API_KEY", "")
    base_url = (
        os.environ.get("OPENAI_BASE_URL")
        or os.environ.get("VYCE_BASE_URL")
        or "https://vyceai.com/v1"
    )
    if not api_key:
        print("OPENAI_API_KEY not set", file=sys.stderr)
        return 2

    run_input = RepositoryInput(
        source=TaskSource.GITHUB_ISSUE, issue_url=args.issue
    )
    ref = parse_github_url(args.issue)

    rows = []
    with tempfile.TemporaryDirectory(prefix="rm-matrix-") as tmp:
        root = Path(tmp)
        # Clone once; the generator/verifier always reset the tree, so
        # sequential model runs can share the workspace safely.
        cache = RepoWorkspace.from_github(ref, root / "cache")
        factory = lambda r, dest, config: RepoWorkspace.from_local(cache.root)

        for model in MODELS:
            started = time.monotonic()
            provider = OpenAIProvider(api_key, base_url=base_url, model=model)
            config = PipelineConfig(
                runs_root=root / "runs",
                planner=ModelPlanner(provider),
                keep_workspace=False,
            )
            record = run_pipeline(
                run_input, config=config, run_id=f"matrix_{model.replace('.', '_')}",
                workspace_factory=factory,
            )
            duration = time.monotonic() - started

            suite = next(
                (c for c in (record.receipt.checks if record.receipt else [])
                 if c.name == "repository-test-suite"), None
            )
            rows.append({
                "model": model,
                "status": record.status.value,
                "planner": record.planner,
                "task_type": record.plan.task_type.value if record.plan else "-",
                "need_more_info": bool(record.plan and record.plan.need_more_info),
                "paths": ",".join(record.artifact.affected_paths) if record.artifact else "-",
                "patch_lines": len(record.artifact.patch.splitlines()) if record.artifact else 0,
                "patch_checks": (
                    ",".join(
                        f"{c.name.split('-')[0]}={c.status.value}"
                        for c in record.receipt.checks
                        if c.name != "repository-test-suite"
                    ) if record.receipt else "-"
                ),
                "suite": suite.status.value if suite else "-",
                "error": record.error.code.value if record.error else "",
                "seconds": round(duration, 1),
                "summary": (record.plan.summary if record.plan else "")[:200],
            })
            print(f"{model}: {rows[-1]['status']} in {rows[-1]['seconds']}s")

        shutil.rmtree(cache.root, ignore_errors=True)

    lines = [
        "# Model Matrix — Real Issue Run",
        "",
        f"Issue: {args.issue} (open, MIT-licensed repository psf/black)",
        f"Generated {datetime.now(timezone.utc).isoformat()} by `scripts/model_matrix.py`.",
        "",
        "| Model | Status | Task type | Planned file | Patch lines | Patch checks | Suite | Time |",
        "|-------|--------|-----------|--------------|-------------|-------------|-------|------|",
    ]
    for r in rows:
        lines.append(
            f"| `{r['model']}` | {r['status']}{' · ' + r['error'] if r['error'] else ''} "
            f"| {r['task_type']} | `{r['paths']}` | {r['patch_lines']} "
            f"| {r['patch_checks']} | {r['suite']} | {r['seconds']}s |"
        )
    lines += ["", "## Plan summaries", ""]
    for r in rows:
        lines.append(f"- **{r['model']}** ({r['planner']}): {r['summary'] or '—'}")
    lines += [
        "",
        "The repository test suite fails for every model in this bare environment",
        "(black's dependencies are not installed) — an honest FAILED with the",
        "captured output, per the verification contract.",
        "",
    ]

    output = Path(args.out)
    output.write_text("\n".join(lines), encoding="utf-8", newline="\n")
    print(f"wrote {output}")
    ok = sum(1 for r in rows if r["status"] == "COMPLETED")
    print(f"{ok}/{len(rows)} models completed")
    return 0 if ok == len(rows) else 1


if __name__ == "__main__":
    raise SystemExit(main())
