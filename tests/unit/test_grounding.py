"""Claim-level grounding validation — the enforcement half of "evidence-first".

The invariant under test: **no final report may present a nonexistent
evidence reference as a verified citation.** A claim whose citations do not
resolve, or whose evidence is structurally invalid, or whose evidence shares
no vocabulary with the claim, is recorded as a hypothesis with a warning.

The validator is deterministic and model-free by design: the verdict must
not come from the same model that produced the claim.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

from repomate_core.contracts import (
    ContributionPlan,
    EvidenceKind,
    EvidenceRecord,
    LicenseInfo,
    LicenseStatus,
    ProposedClaim,
    RepositorySnapshot,
    SupportStatus,
    TaskType,
)
from repomate_core.evidence.grounding import validate_plan_grounding
from repomate_core.repository.workspace import RepoWorkspace

TIMEOUT_DOC = """# Configuration

The client reads `FIXTURE_TIMEOUT` to control the request timeout in
seconds. Retries honour `FIXTURE_RETRIES`.

Set the timeout before constructing the client.
"""


def _git(cwd: Path, *args: str) -> None:
    env = dict(
        os.environ,
        GIT_AUTHOR_NAME="Grounding Bot",
        GIT_AUTHOR_EMAIL="bot@example.invalid",
        GIT_COMMITTER_NAME="Grounding Bot",
        GIT_COMMITTER_EMAIL="bot@example.invalid",
        GIT_TERMINAL_PROMPT="0",
    )
    result = subprocess.run(
        ["git", *args], cwd=str(cwd), capture_output=True, text=True, env=env
    )
    assert result.returncode == 0, f"git {args} failed: {result.stderr}"


@pytest.fixture
def grounded_repo(tmp_path: Path) -> RepoWorkspace:
    """A two-file repo whose line ranges are known exactly."""
    repo = tmp_path / "grounded"
    (repo / "docs").mkdir(parents=True)
    (repo / "README.md").write_text(
        "# fixture\n\nQuickstart for the fixture project.\n", encoding="utf-8", newline="\n"
    )
    (repo / "docs" / "config.md").write_text(TIMEOUT_DOC, encoding="utf-8", newline="\n")
    _git(repo, "init", "-b", "main")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-m", "fixture")
    return RepoWorkspace.from_local(repo)


@pytest.fixture
def snapshot(grounded_repo: RepoWorkspace) -> RepositorySnapshot:
    return RepositorySnapshot(
        owner="acme",
        name="fixture",
        url="https://github.com/acme/fixture",
        default_branch="main",
        commit_sha=grounded_repo.commit_sha,
        license=LicenseInfo(status=LicenseStatus.RECOGNIZED, spdx_id="MIT"),
        readme_path="README.md",
    )


def _evidence(ws: RepoWorkspace) -> list[EvidenceRecord]:
    return [
        EvidenceRecord(
            id="ev1",
            kind=EvidenceKind.DOC,
            path="docs/config.md",
            start_line=1,
            end_line=6,
            snippet=ws.read_text("docs/config.md"),
            rationale="matches task keywords: timeout",
        ),
        EvidenceRecord(
            id="ev2",
            kind=EvidenceKind.DOC,
            path="README.md",
            start_line=1,
            end_line=3,
            snippet=ws.read_text("README.md"),
            rationale="matches task keywords: quickstart",
        ),
    ]


def _plan(
    claims: list[ProposedClaim],
    *,
    evidence_ids: list[str] | None = None,
    summary: str = "Document the FIXTURE_TIMEOUT option in the configuration docs",
) -> ContributionPlan:
    return ContributionPlan(
        task_type=TaskType.DOCUMENTATION,
        summary=summary,
        evidence_ids=evidence_ids if evidence_ids is not None else ["ev1"],
        proposed_claims=claims,
        planned_by="model:openai/gemma4:31b",
    )


def _validate(plan, ws, snapshot):
    return validate_plan_grounding(plan, _evidence(ws), snapshot, workspace=ws)


# -- required case 1: valid evidence id --------------------------------------


class TestValidCitation:
    def test_claim_with_existing_relevant_evidence_is_supported(
        self, grounded_repo, snapshot
    ):
        plan = _plan([
            ProposedClaim(
                text="The client reads FIXTURE_TIMEOUT to control the request timeout",
                evidence_ids=["ev1"],
            )
        ])
        report = _validate(plan, grounded_repo, snapshot)

        assert len(report.claims) == 1
        claim = report.claims[0]
        assert claim.support_status is SupportStatus.SUPPORTED
        assert claim.matched_evidence_ids == ["ev1"]
        assert "timeout" in claim.matched_keywords
        assert report.unresolved_evidence_ids == []
        assert not [
            w for w in report.warnings if w.code == "UNKNOWN_EVIDENCE_ID"
        ]

    def test_supported_claim_counts_are_reported(self, grounded_repo, snapshot):
        plan = _plan([
            ProposedClaim(text="FIXTURE_TIMEOUT controls the request timeout", evidence_ids=["ev1"]),
            ProposedClaim(text="The fixture project has a quickstart", evidence_ids=["ev2"]),
        ])
        report = _validate(plan, grounded_repo, snapshot)

        assert report.supported_claims == 2
        assert report.hypothesis_claims == 0


# -- required case 2: unknown evidence id ------------------------------------


class TestUnknownEvidenceId:
    def test_unknown_id_downgrades_claim_to_hypothesis(self, grounded_repo, snapshot):
        plan = _plan(
            [
                ProposedClaim(
                    text="The client reads FIXTURE_TIMEOUT to control the request timeout",
                    evidence_ids=["ev99"],
                )
            ],
            evidence_ids=[],  # isolate the claim-level citation
        )
        report = _validate(plan, grounded_repo, snapshot)

        claim = report.claims[0]
        assert claim.support_status is SupportStatus.HYPOTHESIS
        assert claim.matched_evidence_ids == []
        assert report.unresolved_evidence_ids == ["ev99"]

        unknown = [w for w in report.warnings if w.code == "UNKNOWN_EVIDENCE_ID"]
        assert len(unknown) == 1
        assert unknown[0].evidence_id == "ev99"

    def test_unknown_id_is_never_a_resolved_citation(self, grounded_repo, snapshot):
        """The acceptance criterion, stated directly."""
        plan = _plan(
            [ProposedClaim(text="Something entirely invented", evidence_ids=["ev99"])],
            evidence_ids=[],
        )
        report = _validate(plan, grounded_repo, snapshot)

        assert "ev99" not in report.resolved_evidence_ids
        assert report.resolved_evidence_ids == []
        assert report.unresolved_evidence_ids == ["ev99"]


# -- required case 3: mixture of valid and unknown ---------------------------


class TestMixedCitations:
    def test_mixture_warns_and_does_not_auto_support(self, grounded_repo, snapshot):
        plan = _plan([
            ProposedClaim(
                text="The client reads FIXTURE_TIMEOUT to control the request timeout",
                evidence_ids=["ev1", "ev99"],
            )
        ])
        report = _validate(plan, grounded_repo, snapshot)

        claim = report.claims[0]
        # One citation resolved, but the claim cites an invented record, so
        # it must not be presented as fully supported.
        assert claim.support_status is SupportStatus.HYPOTHESIS
        assert claim.matched_evidence_ids == ["ev1"]
        assert report.unresolved_evidence_ids == ["ev99"]
        assert any(w.code == "UNKNOWN_EVIDENCE_ID" for w in report.warnings)

    def test_flat_evidence_list_mixture_is_split(self, grounded_repo, snapshot):
        plan = _plan([], evidence_ids=["ev1", "ev2", "ev404"])
        report = _validate(plan, grounded_repo, snapshot)

        assert report.resolved_evidence_ids == ["ev1", "ev2"]
        assert report.unresolved_evidence_ids == ["ev404"]


# -- required case 4: empty references ---------------------------------------


class TestEmptyReferences:
    def test_claim_with_no_citations_is_a_hypothesis(self, grounded_repo, snapshot):
        plan = _plan([ProposedClaim(text="The timeout defaults to 30 seconds", evidence_ids=[])])
        report = _validate(plan, grounded_repo, snapshot)

        claim = report.claims[0]
        assert claim.support_status is SupportStatus.HYPOTHESIS
        assert claim.matched_evidence_ids == []
        assert any(w.code == "NO_EVIDENCE" for w in report.warnings)

    def test_plan_with_no_citations_at_all(self, grounded_repo, snapshot):
        plan = _plan([], evidence_ids=[], summary="Some unsupported assertion")
        report = _validate(plan, grounded_repo, snapshot)

        assert report.resolved_evidence_ids == []
        assert report.unresolved_evidence_ids == []
        assert report.claims
        assert all(
            c.support_status is SupportStatus.HYPOTHESIS for c in report.claims
        )


# -- required case 5: wrong revision / invalid line range --------------------


class TestStructuralRejection:
    def test_line_range_beyond_end_of_file_is_rejected(self, grounded_repo, snapshot):
        evidence = _evidence(grounded_repo)
        evidence[0].end_line = 99_999  # docs/config.md is 6 lines
        plan = _plan([
            ProposedClaim(text="FIXTURE_TIMEOUT controls the timeout", evidence_ids=["ev1"])
        ])
        report = validate_plan_grounding(plan, evidence, snapshot, workspace=grounded_repo)

        assert report.claims[0].support_status is SupportStatus.HYPOTHESIS
        assert any(w.code == "EVIDENCE_LINE_RANGE_INVALID" for w in report.warnings)
        assert report.resolved_evidence_ids == []

    def test_zero_or_inverted_line_range_is_rejected(self, grounded_repo, snapshot):
        evidence = _evidence(grounded_repo)
        evidence[0].start_line = 5
        evidence[0].end_line = 2
        plan = _plan([
            ProposedClaim(text="FIXTURE_TIMEOUT controls the timeout", evidence_ids=["ev1"])
        ])
        report = validate_plan_grounding(plan, evidence, snapshot, workspace=grounded_repo)

        assert any(w.code == "EVIDENCE_LINE_RANGE_INVALID" for w in report.warnings)

    def test_path_missing_from_snapshot_is_rejected(self, grounded_repo, snapshot):
        evidence = _evidence(grounded_repo)
        evidence[0].path = "docs/does_not_exist.md"
        plan = _plan([
            ProposedClaim(text="FIXTURE_TIMEOUT controls the timeout", evidence_ids=["ev1"])
        ])
        report = validate_plan_grounding(plan, evidence, snapshot, workspace=grounded_repo)

        assert any(w.code == "EVIDENCE_PATH_MISSING" for w in report.warnings)
        assert report.claims[0].support_status is SupportStatus.HYPOTHESIS

    def test_wrong_revision_rejects_every_citation(self, grounded_repo, snapshot):
        snapshot.commit_sha = "0" * 40  # workspace is at a different commit
        plan = _plan([
            ProposedClaim(text="FIXTURE_TIMEOUT controls the timeout", evidence_ids=["ev1"])
        ])
        report = _validate(plan, grounded_repo, snapshot)

        assert any(w.code == "EVIDENCE_COMMIT_MISMATCH" for w in report.warnings)
        assert report.claims[0].support_status is SupportStatus.HYPOTHESIS
        assert report.resolved_evidence_ids == []
        assert report.unresolved_evidence_ids == ["ev1"]

    def test_missing_workspace_marks_citations_unverified(self, grounded_repo, snapshot):
        plan = _plan([
            ProposedClaim(text="FIXTURE_TIMEOUT controls the timeout", evidence_ids=["ev1"])
        ])
        report = validate_plan_grounding(
            plan, _evidence(grounded_repo), snapshot, workspace=None
        )

        assert any(
            "checks were skipped" in w.message for w in report.warnings
        )


# -- required case 6: real id, unrelated claim -------------------------------


class TestExistenceIsNotProof:
    def test_real_but_unrelated_evidence_does_not_support_the_claim(
        self, grounded_repo, snapshot
    ):
        """ev2 is a real record (the README quickstart). Citing it for a
        claim about retry semantics must not count as support."""
        plan = _plan([
            ProposedClaim(
                text="Retries honour the FIXTURE_RETRIES environment variable",
                evidence_ids=["ev2"],
            )
        ])
        report = _validate(plan, grounded_repo, snapshot)

        claim = report.claims[0]
        assert claim.support_status is SupportStatus.HYPOTHESIS
        assert claim.matched_evidence_ids == []
        assert any(
            w.code == "CLAIM_NOT_SUPPORTED_BY_EVIDENCE" for w in report.warnings
        )

    def test_swapping_evidence_changes_the_verdict(self, grounded_repo, snapshot):
        """Same claim, right evidence vs. wrong evidence."""
        text = "Retries honour the FIXTURE_RETRIES environment variable"
        right = _validate(_plan([ProposedClaim(text=text, evidence_ids=["ev1"])]),
                          grounded_repo, snapshot)
        wrong = _validate(_plan([ProposedClaim(text=text, evidence_ids=["ev2"])]),
                          grounded_repo, snapshot)

        assert right.claims[0].support_status is SupportStatus.SUPPORTED
        assert wrong.claims[0].support_status is SupportStatus.HYPOTHESIS

    def test_claim_with_no_checkable_vocabulary_is_not_supported(
        self, grounded_repo, snapshot
    ):
        plan = _plan([
            ProposedClaim(text="It is fine.", evidence_ids=["ev1"])
        ])
        report = _validate(plan, grounded_repo, snapshot)

        assert report.claims[0].support_status is SupportStatus.HYPOTHESIS

    def test_repository_name_alone_is_not_support(self, grounded_repo, snapshot):
        """Found by an adversarial check against a real run of psf/black.

        Almost every snippet in that repository contains the word "black",
        so a claim that merely mentions the project name looked supported by
        any record at all. Matching only the repository's own name is not
        evidence.
        """
        snapshot.name = "fixture"
        plan = _plan(
            [ProposedClaim(text="The fixture project is well documented", evidence_ids=["ev2"])],
            evidence_ids=[],
        )
        report = _validate(plan, grounded_repo, snapshot)

        assert report.claims[0].support_status is SupportStatus.HYPOTHESIS
        assert report.claims[0].matched_keywords == []
        assert any(
            w.code == "CLAIM_NOT_SUPPORTED_BY_EVIDENCE" for w in report.warnings
        )

    def test_ubiquitous_token_is_not_support(self, grounded_repo, snapshot):
        """A token present in most records cannot discriminate between them."""
        evidence = _evidence(grounded_repo)
        for record in evidence:
            record.snippet = f"commonword {record.snippet}"
        plan = _plan(
            [ProposedClaim(text="commonword appears here", evidence_ids=["ev1"])],
            evidence_ids=[],
        )
        report = validate_plan_grounding(
            plan, evidence, snapshot, workspace=grounded_repo
        )

        assert report.claims[0].support_status is SupportStatus.HYPOTHESIS

    def test_specific_vocabulary_still_supports(self, grounded_repo, snapshot):
        """The weak-token rule must not make the validator useless."""
        snapshot.name = "fixture"
        plan = _plan(
            [
                ProposedClaim(
                    text="The client reads FIXTURE_TIMEOUT to control the request timeout",
                    evidence_ids=["ev1"],
                )
            ],
            evidence_ids=[],
        )
        report = _validate(plan, grounded_repo, snapshot)

        assert report.claims[0].support_status is SupportStatus.SUPPORTED
        assert "timeout" in report.claims[0].matched_keywords


# -- fallback: no proposed_claims -------------------------------------------


class TestPlanLevelFallback:
    def test_summary_is_validated_when_model_supplies_no_claims(
        self, grounded_repo, snapshot
    ):
        plan = _plan(
            [],
            evidence_ids=["ev1"],
            summary="Document the FIXTURE_TIMEOUT request timeout option",
        )
        report = _validate(plan, grounded_repo, snapshot)

        assert report.claims, "the plan summary must still be validated"
        assert report.claims[0].text.startswith("Document the FIXTURE_TIMEOUT")
        assert report.claims[0].support_status is SupportStatus.SUPPORTED

    def test_summary_with_unresolvable_citation_is_a_hypothesis(
        self, grounded_repo, snapshot
    ):
        plan = _plan([], evidence_ids=["ev99"], summary="Document the timeout option")
        report = _validate(plan, grounded_repo, snapshot)

        assert report.claims[0].support_status is SupportStatus.HYPOTHESIS
        assert report.unresolved_evidence_ids == ["ev99"]


# -- audit trail -------------------------------------------------------------


class TestAuditTrail:
    def test_raw_model_output_is_preserved_for_audit(self, grounded_repo, snapshot):
        plan = _plan([ProposedClaim(text="FIXTURE_TIMEOUT controls the timeout", evidence_ids=["ev1"])])
        plan.raw_response = '{"summary": "...", "evidence_ids": ["ev1"]}'
        report = _validate(plan, grounded_repo, snapshot)

        # Validation must not mutate the model's original output.
        assert plan.raw_response == '{"summary": "...", "evidence_ids": ["ev1"]}'
        assert report.claims[0].evidence_ids == ["ev1"]

    def test_warnings_carry_the_claim_text_for_review(self, grounded_repo, snapshot):
        plan = _plan([ProposedClaim(text="An invented assertion about widgets", evidence_ids=["ev99"])])
        report = _validate(plan, grounded_repo, snapshot)

        unknown = [w for w in report.warnings if w.code == "UNKNOWN_EVIDENCE_ID"]
        assert unknown[0].claim_text == "An invented assertion about widgets"
