"""Markdown documents published alongside a run's primary diff.

Two PS04 outputs are documents, not diffs:

- ``CONTRIBUTION_PLAN.md`` — the plan, its evidence citations, grounding
  verdict, limitations and open questions. Published for every run that has
  a plan, including ``NEED_MORE_INFO`` runs, because the plan is the
  contribution artefact a reviewer can act on even when code generation is
  correctly deferred.
- ``REPRO_CHECKLIST.md`` — evidence-guided reproduction and verification
  steps for a ``BUG_FIX`` plan. It is explicit about what is *not* known: it
  never claims a reproduction happened, and records the baseline/post-patch
  comparison once verification ran.

Rendering is deterministic and uses only persisted record data, so the same
run always produces the same downloads.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from repomate_core.contracts import (
    ArtifactDocument,
    ArtifactKind,
    TaskType,
)

if TYPE_CHECKING:  # pragma: no cover - typing only
    from repomate_core.contracts import RunRecord

_MAX_SNIPPET_CHARS = 600
_MAX_ITEMS = 12


def build_documents(record: "RunRecord") -> list[ArtifactDocument]:
    """Return the documents this record should publish."""
    if record.plan is None:
        return []
    documents = [
        ArtifactDocument(
            name="CONTRIBUTION_PLAN.md",
            kind=ArtifactKind.CONTRIBUTION_PLAN,
            content=render_contribution_plan(record),
            generated_by=record.plan.planned_by,
        )
    ]
    if record.plan.task_type is TaskType.BUG_FIX:
        documents.append(
            ArtifactDocument(
                name="REPRO_CHECKLIST.md",
                kind=ArtifactKind.REPRO_CHECKLIST,
                content=render_repro_checklist(record),
                generated_by=record.plan.planned_by,
            )
        )
    return documents


def render_contribution_plan(record: "RunRecord") -> str:
    plan = record.plan
    assert plan is not None  # caller guarantees this; keeps type narrow

    lines: list[str] = [
        "# Contribution Plan",
        "",
        f"- **Repository:** `{_repo_slug(record)}`",
        f"- **Pinned commit:** `{_commit(record)}`",
        f"- **Planner:** `{plan.planned_by or record.planner or 'unknown'}`",
        f"- **Task type:** `{plan.task_type.value}`",
        f"- **Run status:** `{record.status.value}`",
    ]
    if record.snapshot is not None:
        license_info = record.snapshot.license
        lines.append(
            f"- **License:** `{license_info.status.value}`"
            + (f" ({license_info.spdx_id})" if license_info.spdx_id else "")
        )
    lines += ["", "## Task", "", _block(_task_text(record)), "", "## Summary", "", _block(plan.summary)]

    if plan.planned_changes:
        lines += ["", "## Planned changes", "", "| Path | Change | Rationale |", "|---|---|---|"]
        for change in plan.planned_changes[:_MAX_ITEMS]:
            lines.append(
                f"| `{_cell(change.path)}` | {change.change_type} | "
                f"{_cell(change.rationale)} |"
            )

    if plan.acceptance_criteria:
        lines += ["", "## Acceptance criteria", ""]
        lines += [f"- {item}" for item in plan.acceptance_criteria[:_MAX_ITEMS]]

    if record.evidence:
        lines += ["", "## Evidence consulted", ""]
        for evidence in record.evidence[:_MAX_ITEMS]:
            location = evidence.path
            if evidence.start_line is not None:
                location += f":{evidence.start_line}-{evidence.end_line}"
            lines.append(f"- `{evidence.id}` — `{location}` — {evidence.rationale}")
            snippet = evidence.snippet.strip()
            if snippet:
                if len(snippet) > _MAX_SNIPPET_CHARS:
                    snippet = snippet[:_MAX_SNIPPET_CHARS].rstrip() + "…"
                lines += ["", "  ```", *[f"  {line}" for line in snippet.splitlines()], "  ```"]
        if len(record.evidence) > _MAX_ITEMS:
            lines.append(
                f"- … {len(record.evidence) - _MAX_ITEMS} more record(s) in the run evidence set"
            )

    if record.grounding is not None:
        grounding = record.grounding
        lines += ["", "## Grounding", ""]
        lines.append(
            f"- Resolved citations: {len(grounding.resolved_evidence_ids)}"
            f" of {len(grounding.resolved_evidence_ids) + len(grounding.unresolved_evidence_ids)}"
        )
        if grounding.unresolved_evidence_ids:
            lines.append(
                "- Unresolved citation ids: "
                + ", ".join(f"`{item}`" for item in grounding.unresolved_evidence_ids[:10])
            )
        for claim in grounding.claims[:10]:
            lines.append(
                f"- `{claim.support_status.value}` — {claim.text[:300]}"
            )
        for warning in grounding.warnings[:10]:
            lines.append(f"- Warning `{warning.code}`: {warning.message}")

    if plan.limitations:
        lines += ["", "## Limitations", ""]
        lines += [f"- {item}" for item in plan.limitations[:_MAX_ITEMS]]

    if plan.questions:
        lines += ["", "## Open questions", ""]
        lines += [f"- {item}" for item in plan.questions[:_MAX_ITEMS]]

    if record.error is not None:
        lines += [
            "",
            "## Run error",
            "",
            f"- `{record.error.code.value}` — {record.error.message}",
        ]

    lines += [
        "",
        "## Honest status",
        "",
        _honest_status(record),
        "",
        "<!-- Generated by RepoMate from persisted run data. -->",
        "",
    ]
    return "\n".join(lines)


def render_repro_checklist(record: "RunRecord") -> str:
    plan = record.plan
    assert plan is not None

    lines: list[str] = [
        "# Reproduction Checklist",
        "",
        "- **Repository:** `" + _repo_slug(record) + "`",
        "- **Pinned commit:** `" + _commit(record) + "`",
        "- **Planner:** `" + (plan.planned_by or record.planner or "unknown") + "`",
        "- **Run status:** `" + record.status.value + "`",
        "",
        "> These steps are derived from the task text and the cited evidence.",
        "> RepoMate did not observe the reported failure itself, so the checklist",
        "> asks you to record whether it reproduces rather than asserting that it does.",
        "",
        "## Reported task",
        "",
        _block(_task_text(record)),
        "",
        "## Expected behaviour",
        "",
    ]
    if plan.acceptance_criteria:
        lines += [f"- {item}" for item in plan.acceptance_criteria[:_MAX_ITEMS]]
    else:
        lines.append("- Not stated in the task or plan; capture it before changing code.")

    lines += ["", "## Environment", ""]
    if record.snapshot is not None:
        lines.append(f"- Commit: `{record.snapshot.commit_sha}`")
        languages = sorted(
            record.snapshot.languages.items(), key=lambda item: item[1], reverse=True
        )
        if languages:
            lines.append(
                "- Languages: "
                + ", ".join(f"{name} ({pct:g}%)" for name, pct in languages[:5])
            )
    if record.test_guidance is not None:
        guidance = record.test_guidance
        if guidance.run_command:
            lines.append(f"- Full suite command: `{guidance.run_command}`")
        if guidance.focused_command:
            lines.append(f"- Focused command: `{guidance.focused_command}`")
        if guidance.note:
            lines.append(f"- Test guidance note: {guidance.note}")

    lines += ["", "## Evidence-guided steps", ""]
    steps: list[str] = [
        f"Check out the pinned commit `{_commit(record)}`.",
    ]
    if record.test_guidance is not None and record.test_guidance.relevant_tests:
        tests = ", ".join(
            f"`{item.path}`" for item in record.test_guidance.relevant_tests[:5]
        )
        steps.append(f"Inspect the evidence-matched test file(s): {tests}.")
    if record.test_guidance is not None and record.test_guidance.focused_command:
        steps.append(
            "Run the focused command "
            f"`{record.test_guidance.focused_command}` and record the exit code and output."
        )
    if record.test_guidance is not None and record.test_guidance.run_command:
        steps.append(
            "Run the full suite "
            f"`{record.test_guidance.run_command}`; note any pre-existing failures."
        )
    steps.append(
        "Capture the observed behaviour, exit code and relevant output before applying a fix."
    )
    lines += [f"{index}. {step}" for index, step in enumerate(steps, start=1)]

    relevant = [
        evidence
        for evidence in record.evidence
        if evidence.kind.value in ("SOURCE", "TEST")
    ]
    if relevant:
        lines += ["", "## Cited evidence", ""]
        for evidence in relevant[:_MAX_ITEMS]:
            location = evidence.path
            if evidence.start_line is not None:
                location += f":{evidence.start_line}-{evidence.end_line}"
            lines.append(f"- `{location}` — {evidence.rationale}")

    if plan.questions:
        lines += ["", "## Questions to resolve before fixing", ""]
        lines += [f"- {item}" for item in plan.questions[:_MAX_ITEMS]]

    lines += ["", "## Verification recorded by RepoMate", ""]
    if record.receipt is not None:
        comparison = record.receipt.comparison
        if comparison is not None:
            lines += [
                f"- Baseline: `{comparison.baseline.status.value}`"
                + (f", exit `{comparison.baseline.exit_code}`" if comparison.baseline.exit_code is not None else "")
                + (f", command `{comparison.baseline.command}`" if comparison.baseline.command else ""),
                f"- Post-patch: `{comparison.post_patch.status.value}`"
                + (f", exit `{comparison.post_patch.exit_code}`" if comparison.post_patch.exit_code is not None else "")
                + (f", command `{comparison.post_patch.command}`" if comparison.post_patch.command else ""),
                f"- Comparison: `{comparison.outcome.value}`",
                f"- Statement: {comparison.interpretation}",
            ]
        else:
            lines.append(
                "- No baseline/post-patch comparison was recorded for this run."
            )
        for check in record.receipt.checks:
            if check.name == "repository-test-suite":
                lines.append(
                    f"- Repository suite: `{check.status.value}`"
                    + (f", exit `{check.exit_code}`" if check.exit_code is not None else "")
                    + (f" — {check.reason}" if check.reason else "")
                )
    else:
        lines.append("- Verification did not run before this checklist was published.")
    lines += [
        "",
        "## Record your observation",
        "",
        "- [ ] The failure reproduces at the pinned commit (attach output or exit code).",
        "- [ ] The cited evidence is the code path involved.",
        "- [ ] The focused command still fails after a clean checkout.",
        "- [ ] A proposed fix is a separate, reviewable diff.",
        "",
        "<!-- Generated by RepoMate from persisted run data. -->",
        "",
    ]
    return "\n".join(lines)


def _task_text(record: "RunRecord") -> str:
    if record.input.task:
        return record.input.task.strip()
    if record.issue is not None:
        body = record.issue.body.strip()
        return f"{record.issue.title.strip()}\n\n{body}" if body else record.issue.title.strip()
    return "No task text recorded."


def _repo_slug(record: "RunRecord") -> str:
    if record.snapshot is not None:
        return f"{record.snapshot.owner}/{record.snapshot.name}"
    raw = record.input.repo_url or record.input.issue_url or "unknown"
    return raw.removeprefix("https://github.com/").strip("/")


def _commit(record: "RunRecord") -> str:
    return record.snapshot.commit_sha if record.snapshot is not None else "unknown"


def _honest_status(record: "RunRecord") -> str:
    receipt = record.receipt
    if receipt is None:
        return (
            "No verification receipt was produced for this run. The plan and "
            "evidence above are published, but no check result is claimed."
        )
    if receipt.comparison is None:
        return (
            "Verification did not execute a baseline/post-patch comparison; "
            "read the receipt's NOT_RUN reasons before treating any check as evidence."
        )
    if receipt.comparison.outcome.value == "CONSISTENT_IMPROVEMENT":
        return (
            "The selected checks improved consistently between the baseline and "
            "patched checkouts. This is not proof that the issue is fully resolved."
        )
    if receipt.comparison.outcome.value == "NO_REGRESSION_DETECTED":
        return (
            "The selected checks show no regression; they do not prove the issue "
            "was fixed."
        )
    return (
        "The selected checks do not establish a resolution. Read the comparison "
        "and the receipt's reasons before relying on this artifact."
    )


def _block(text: str) -> str:
    value = (text or "").strip()
    return value if value else "_Not provided._"


def _cell(text: str) -> str:
    return (text or "").replace("|", "\\|").replace("\n", " ").strip()
