"""Deterministic task classification from free text."""

from __future__ import annotations

from repomate_core.contracts import TaskType

_CLASSIFY_RULES: tuple[tuple[TaskType, tuple[str, ...]], ...] = (
    (TaskType.TEST, ("test", "tests", "coverage", "pytest", "unit test", "regression test")),
    (TaskType.DOCUMENTATION, ("document", "documentation", "docs", "readme", "docstring", "example", "usage guide", "clarif")),
    (TaskType.REFACTOR, ("refactor", "clean up", "rename", "simplify", "modernize")),
    (TaskType.BUG_FIX, ("bug", "fix", "crash", "error", "wrong", "fails", "broken", "regression", "incorrect")),
    (TaskType.FEATURE, ("add", "support", "implement", "feature", "enable", "introduce")),
)

_DEFAULT_CRITERIA = (
    "Patch applies cleanly to the pinned commit",
    "Only paths permitted by the artifact policy are modified",
    "The change addresses the stated task",
)


def classify_task(task_text: str) -> TaskType:
    lowered = task_text.lower()
    for task_type, needles in _CLASSIFY_RULES:
        if any(needle in lowered for needle in needles):
            return task_type
    return TaskType.UNKNOWN


def default_acceptance_criteria() -> list[str]:
    return list(_DEFAULT_CRITERIA)
