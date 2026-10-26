"""Grounding is enforced by the pipeline, not just available as a function.

The unit tests prove the validator's rules. These prove the wiring: a plan
that reaches the pipeline is validated, the verdict is persisted on the run
record, and a fabricated citation cannot survive into a completed run's
report as a verified citation.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from repomate_core.contracts import (
    ContributionPlan,
    PlannedChange,
    ProposedClaim,
    RepositoryInput,
    RunStatus,
    SupportStatus,
    TaskSource,
    TaskType,
)
from repomate_core.orchestration.pipeline import run_pipeline
from repomate_core.orchestration.pipeline_config import PipelineConfig
from repomate_core.repository.workspace import RepoWorkspace


class GroundedPlanner:
    """A model-like planner that supplies claim-level citations."""

    name = "model:openai/gemma4:31b"

    def __init__(self, claims, *, evidence_ids=None):
        self._claims = claims
        self._evidence_ids = evidence_ids

    def plan(self, task_text, snapshot, evidence):
        ids = self._evidence_ids
        if ids is None:
            ids = [e.id for e in evidence[:3]]
        return ContributionPlan(
            task_type=TaskType.DOCUMENTATION,
            summary="Document the FIXTURE_TIMEOUT request timeout option",
            planned_changes=[
                PlannedChange(path="README.md", change_type="MODIFY", rationale="")
            ],
            evidence_ids=ids,
            proposed_claims=self._claims,
            content_draft=(
                "Set `FIXTURE_TIMEOUT` to control the request timeout in seconds.\n\n"
                "Retries honour `FIXTURE_RETRIES`."
            ),
            planned_by=self.name,
        )


def _factory(local_repo: Path):
    return lambda ref, dest, config: RepoWorkspace.from_local(local_repo)


def _run(planner, repo, tmp_path, task_input):
    return run_pipeline(
        task_input,
        config=PipelineConfig(runs_root=tmp_path / "runs", planner=planner),
        workspace_factory=_factory(repo),
    )


def test_grounding_report_is_persisted_on_the_run(local_repo, docs_task_input, tmp_path):
    planner = GroundedPlanner([
        ProposedClaim(
            text="The client reads FIXTURE_TIMEOUT to control the request timeout",
            evidence_ids=["ev1"],
        )
    ])
    record = _run(planner, local_repo, tmp_path, docs_task_input)

    assert record.status is RunStatus.COMPLETED
    assert record.grounding is not None
    assert record.grounding.claims
    assert record.grounding.supported_claims >= 1


def test_fabricated_citation_never_becomes_a_verified_citation(
    local_repo, docs_task_input, tmp_path
):
    """The acceptance criterion, end to end."""
    planner = GroundedPlanner(
        [
            ProposedClaim(
                text="The client reads FIXTURE_TIMEOUT to control the request timeout",
                evidence_ids=["ev99"],
            )
        ],
        evidence_ids=["ev99"],
    )
    record = _run(planner, local_repo, tmp_path, docs_task_input)

    assert record.grounding is not None
    assert "ev99" not in record.grounding.resolved_evidence_ids
    assert "ev99" in record.grounding.unresolved_evidence_ids
    assert all(
        claim.support_status is SupportStatus.HYPOTHESIS
        for claim in record.grounding.claims
    )
    assert any(
        w.code == "UNKNOWN_EVIDENCE_ID" for w in record.grounding.warnings
    )


def test_mixed_citations_do_not_yield_a_supported_claim(
    local_repo, docs_task_input, tmp_path
):
    planner = GroundedPlanner([
        ProposedClaim(
            text="The client reads FIXTURE_TIMEOUT to control the request timeout",
            evidence_ids=["ev1", "ev99"],
        )
    ])
    record = _run(planner, local_repo, tmp_path, docs_task_input)

    assert record.grounding is not None
    assert record.grounding.hypothesis_claims >= 1
    assert "ev99" in record.grounding.unresolved_evidence_ids


def test_raw_model_output_survives_validation(local_repo, docs_task_input, tmp_path):
    """The model's original output stays auditable next to the verdict."""
    planner = GroundedPlanner([
        ProposedClaim(text="FIXTURE_TIMEOUT controls the timeout", evidence_ids=["ev1"])
    ])
    record = _run(planner, local_repo, tmp_path, docs_task_input)

    assert record.plan is not None
    assert record.plan.proposed_claims
    # The plan the validator saw is the plan the model produced.
    assert record.plan.proposed_claims[0].evidence_ids == ["ev1"]


def test_grounding_stage_emits_an_event(local_repo, docs_task_input, tmp_path):
    planner = GroundedPlanner([
        ProposedClaim(text="FIXTURE_TIMEOUT controls the timeout", evidence_ids=["ev1"])
    ])
    record = _run(planner, local_repo, tmp_path, docs_task_input)

    messages = " ".join(event.message for event in record.events)
    assert "Grounding:" in messages


def test_need_more_info_runs_are_still_grounded(local_repo, docs_task_input, tmp_path):
    """Found by a live run of psf/black: a plan that stops to ask a question
    still makes assertions, so its citations must be validated too. The
    grounding stage used to sit behind the NEED_MORE_INFO early return."""

    class AskingPlanner:
        name = "model:openai/gemma4:31b"

        def plan(self, task_text, snapshot, evidence):
            return ContributionPlan(
                task_type=TaskType.DOCUMENTATION,
                summary="The default line length is 88 characters",
                evidence_ids=["ev99"],
                proposed_claims=[
                    ProposedClaim(
                        text="The default line length is 88 characters",
                        evidence_ids=["ev99"],
                    )
                ],
                need_more_info=True,
                questions=["What is the exact default line length?"],
                planned_by=self.name,
            )

    record = _run(AskingPlanner(), local_repo, tmp_path, docs_task_input)

    assert record.status is RunStatus.NEED_MORE_INFO
    assert record.grounding is not None, "an early-stopping plan must still be validated"
    assert "ev99" in record.grounding.unresolved_evidence_ids
    assert record.grounding.claims[0].support_status is SupportStatus.HYPOTHESIS
