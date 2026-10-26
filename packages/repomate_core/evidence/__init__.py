"""Evidence retrieval: locate and cite the files that justify a plan."""

from repomate_core.evidence.collector import (
    RetrievalOutcome,
    collect_evidence,
    collect_evidence_with_report,
)
from repomate_core.evidence.grounding import validate_plan_grounding
from repomate_core.evidence.tools import ToolLoopOutcome, run_tool_loop
from repomate_core.evidence.validation import (
    EvidenceValidation,
    validate_retrieved_evidence,
)

__all__ = [
    "EvidenceValidation",
    "RetrievalOutcome",
    "ToolLoopOutcome",
    "collect_evidence",
    "collect_evidence_with_report",
    "run_tool_loop",
    "validate_plan_grounding",
    "validate_retrieved_evidence",
]
