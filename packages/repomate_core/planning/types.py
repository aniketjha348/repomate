"""The planner contract shared by every strategy."""

from __future__ import annotations

from typing import Protocol

from repomate_core.contracts import (
    ContributionPlan,
    EvidenceRecord,
    RepositorySnapshot,
)


class Planner(Protocol):
    name: str

    def plan(
        self,
        task_text: str,
        snapshot: RepositorySnapshot,
        evidence: list[EvidenceRecord],
    ) -> ContributionPlan: ...
