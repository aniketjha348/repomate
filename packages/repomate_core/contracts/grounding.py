"""Claim-level grounding contracts — the enforcement half of "evidence-first".

A plan is only evidence-first if its citations are actually checked. These
models record, per claim, which evidence resolved and whether the cited
evidence is on-topic for the claim.

``SupportStatus`` is deliberately fail-safe: a claim starts as
``HYPOTHESIS`` and is only promoted to ``SUPPORTED`` by the deterministic
validator in :mod:`repomate_core.evidence.grounding`. A model cannot mark
its own claim supported.
"""

from __future__ import annotations

import enum
from typing import Literal

from pydantic import BaseModel


class SupportStatus(str, enum.Enum):
    """How well a claim is bound to the run's actual evidence."""

    SUPPORTED = "supported"
    HYPOTHESIS = "hypothesis"


GroundingWarningCode = Literal[
    "UNKNOWN_EVIDENCE_ID",
    "NO_EVIDENCE",
    "CLAIM_NOT_SUPPORTED_BY_EVIDENCE",
    "EVIDENCE_PATH_MISSING",
    "EVIDENCE_LINE_RANGE_INVALID",
    "EVIDENCE_COMMIT_MISMATCH",
]


class GroundedClaim(BaseModel):
    """One assertion the plan relies on, with the evidence behind it.

    ``support_status`` is assigned by the validator, never by the model.
    """

    text: str
    evidence_ids: list[str] = []
    support_status: SupportStatus = SupportStatus.HYPOTHESIS
    # Audit trail, so a reviewer can see *why* the status is what it is.
    matched_evidence_ids: list[str] = []
    matched_keywords: list[str] = []


class GroundingWarning(BaseModel):
    """A citation that did not survive validation, with the reason."""

    code: GroundingWarningCode
    message: str
    evidence_id: str = ""
    claim_text: str = ""


class GroundingReport(BaseModel):
    """Outcome of validating every claim and citation in a plan."""

    claims: list[GroundedClaim] = []
    warnings: list[GroundingWarning] = []
    resolved_evidence_ids: list[str] = []
    unresolved_evidence_ids: list[str] = []

    @property
    def supported_claims(self) -> int:
        return sum(
            1 for c in self.claims if c.support_status is SupportStatus.SUPPORTED
        )

    @property
    def hypothesis_claims(self) -> int:
        return sum(
            1 for c in self.claims if c.support_status is SupportStatus.HYPOTHESIS
        )
