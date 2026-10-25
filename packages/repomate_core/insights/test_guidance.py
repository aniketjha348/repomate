"""\"Which tests should I run?\" — answered from evidence, honestly.

Relevant tests come from the evidence collector's TEST records (files
whose names or content matched the task). The run command comes from
toolchain detection. The note is explicit that selection is keyword-based
and the full suite is the authoritative check — matching the PS04 rule
of never overstating what was verified.
"""

from __future__ import annotations

from repomate_core.contracts import (
    EvidenceRecord,
    RepositorySnapshot,
    TestGuidance,
)
from repomate_core.repository.workspace import RepoWorkspace
from repomate_core.verification.sandbox import detect_test_command


def build_test_guidance(
    ws: RepoWorkspace,
    snapshot: RepositorySnapshot,
    evidence: list[EvidenceRecord],
) -> TestGuidance:
    command = detect_test_command(ws)
    relevant = [
        {"path": r.path, "reason": r.rationale}
        for r in evidence
        if r.kind.value == "TEST"
    ][:5]

    if command is None:
        return TestGuidance(
            run_command=None,
            relevant_tests=relevant,
            note=(
                "No supported test command detected (process sandbox supports "
                "pytest and make). Selection above is keyword-based; there is "
                "nothing this environment can execute."
            ),
        )

    return TestGuidance(
        run_command=command.display,
        focused_command=_focused_command(command.display, relevant),
        relevant_tests=relevant,
        note=(
            "Selection is keyword-based — start with the files above, then run "
            "the full suite as the authoritative check. The verification stage "
            f"already executed the full suite ({command.display})."
        ) if relevant else (
            "No test file matched this task by keyword; run the full suite "
            "as the authoritative check."
        ),
    )


def _focused_command(display: str, relevant: list[dict]) -> str | None:
    """A best-effort narrowed command, e.g. pytest with test file args."""
    if not relevant or "pytest" not in display:
        return None
    args = " ".join(t["path"] for t in relevant[:3])
    return f"python -m pytest -q {args}"
