"""Deterministic claim-level grounding validation.

The planner proposes; this module decides. A claim is only ``SUPPORTED``
when the evidence it cites:

1. exists in this run (an unknown ``ev99`` is never a citation),
2. is structurally valid against the pinned snapshot (path present, line
   range inside the file, workspace still at the recorded commit), and
3. is lexically on-topic for the claim — citing a real record that has
   nothing to do with the assertion is not support.

Everything else becomes ``HYPOTHESIS`` with a recorded warning. The verdict
is deliberately deterministic and model-free: it must not depend on the same
model that produced the claim.

Honest limitation: relevance is lexical (keyword overlap), not semantic. It
can therefore pass a claim that happens to share generic vocabulary with
unrelated evidence. It cannot manufacture support for a claim whose
citations do not exist, which is the failure this boundary exists to stop.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, Iterable, Optional

from repomate_core.contracts import (
    ContributionPlan,
    EvidenceRecord,
    GroundedClaim,
    GroundingReport,
    GroundingWarning,
    RepositorySnapshot,
    SupportStatus,
)
from repomate_core.evidence.keywords import extract_keywords

if TYPE_CHECKING:  # pragma: no cover - typing only
    from repomate_core.repository.workspace import RepoWorkspace

# Relevance is morphological, not prefix-based: tokens are lightly stemmed
# and then compared exactly (or with a single-character remainder, which
# covers the silent-e case: "excluding" → "exclud" ~ "exclude").
# A raw 5-character prefix rule was tried first and wrongly matched
# "fixture_retries" against "fixture"; this is stricter.
_TOKEN_RE = re.compile(r"[A-Za-z][A-Za-z0-9_-]{2,}")
_LINE_COUNT_READ_CAP = 2_000_000

# Longest first, so "ies" is tried before "s".
_SUFFIXES: tuple[tuple[str, str], ...] = (
    ("ies", "y"),
    ("ing", ""),
    ("ed", ""),
    ("es", ""),
    ("s", ""),
)
_MIN_STEM = 4


def validate_plan_grounding(
    plan: ContributionPlan,
    evidence: list[EvidenceRecord],
    snapshot: RepositorySnapshot,
    *,
    workspace: Optional["RepoWorkspace"] = None,
) -> GroundingReport:
    """Validate every citation in ``plan`` against this run's evidence.

    ``workspace`` enables the structural checks (path/line/commit). Without
    it those checks are skipped and the report says so, rather than
    pretending they passed.
    """
    index = {record.id: record for record in evidence}
    warnings: list[GroundingWarning] = []
    # Tokens that cannot distinguish one record from another. Matching only
    # these is not support: see ``_non_discriminating_tokens``.
    weak_tokens = _non_discriminating_tokens(evidence, snapshot)

    commit_ok = _commit_matches(snapshot, workspace)
    if not commit_ok:
        warnings.append(
            GroundingWarning(
                code="EVIDENCE_COMMIT_MISMATCH",
                message=(
                    "the workspace is no longer at the pinned commit "
                    f"{snapshot.commit_sha[:10]}; no citation can be verified"
                ),
            )
        )
    if workspace is None:
        warnings.append(
            GroundingWarning(
                code="EVIDENCE_PATH_MISSING",
                message=(
                    "no workspace was available, so path, line-range and commit "
                    "checks were skipped; citations are unverified"
                ),
            )
        )

    # 1) Structural integrity of each evidence record.
    rejected: dict[str, str] = {}
    if workspace is not None:
        for record in evidence:
            code = _record_integrity(record, workspace)
            if code is None:
                continue
            rejected[record.id] = code
            warnings.append(
                GroundingWarning(
                    code=code,  # type: ignore[arg-type]
                    message=_integrity_message(code, record),
                    evidence_id=record.id,
                )
            )

    # 2) Claim-level grounding.
    claims: list[GroundedClaim] = []
    for text, cited_ids in _claim_sources(plan):
        matched, claim_warnings = _resolve_claim(
            text, cited_ids, index, rejected, weak_tokens, commit_ok=commit_ok
        )
        warnings.extend(claim_warnings)
        # Strict rule: a claim is only SUPPORTED when *every* citation it
        # makes resolves. One invented reference is enough to make the
        # whole assertion a hypothesis — otherwise a model could pad a
        # real citation with fabricated ones and keep the "supported"
        # label, which is exactly the failure this boundary exists to stop.
        fully_cited = bool(cited_ids) and all(
            eid in index and eid not in rejected and commit_ok for eid in cited_ids
        )
        claims.append(
            GroundedClaim(
                text=text,
                evidence_ids=list(cited_ids),
                support_status=(
                    SupportStatus.SUPPORTED
                    if matched and fully_cited
                    else SupportStatus.HYPOTHESIS
                ),
                matched_evidence_ids=matched,
                matched_keywords=_matched_keywords(text, matched, index, weak_tokens),
            )
        )

    # 3) Audit of every citation the plan makes — the flat list *and* the
    #    claim-level citations — so a report can never present an unresolved
    #    reference as a verified citation, wherever it appeared.
    cited_everywhere = _dedupe(
        list(plan.evidence_ids)
        + [eid for _text, ids in _claim_sources(plan) for eid in ids]
    )
    resolved: list[str] = []
    unresolved: list[str] = []
    for evidence_id in cited_everywhere:
        if evidence_id in index and evidence_id not in rejected and commit_ok:
            resolved.append(evidence_id)
        else:
            unresolved.append(evidence_id)
            if evidence_id not in index:
                warnings.append(
                    GroundingWarning(
                        code="UNKNOWN_EVIDENCE_ID",
                        message=(
                            f"cited evidence {evidence_id!r} does not exist in this "
                            "run's evidence set"
                        ),
                        evidence_id=evidence_id,
                    )
                )

    return GroundingReport(
        claims=claims,
        warnings=_dedupe_warnings(warnings),
        resolved_evidence_ids=resolved,
        unresolved_evidence_ids=unresolved,
    )


def _dedupe_warnings(
    warnings: list[GroundingWarning],
) -> list[GroundingWarning]:
    """One warning per (code, evidence id).

    A claim-level citation and the plan's flat citation list can name the
    same bad id; reporting it twice adds noise without adding information.
    The claim-level warning wins because it carries the claim text.
    """
    out: list[GroundingWarning] = []
    position: dict[tuple[str, str], int] = {}
    for warning in warnings:
        key = (warning.code, warning.evidence_id)
        existing = position.get(key)
        if existing is None:
            position[key] = len(out)
            out.append(warning)
        elif warning.claim_text and not out[existing].claim_text:
            out[existing] = warning
    return out


# -- claim sources ------------------------------------------------------------


def _claim_sources(plan: ContributionPlan) -> list[tuple[str, list[str]]]:
    """The assertion-bearing parts of a plan, each with its citations.

    When the model supplied ``proposed_claims`` those are used verbatim —
    the model gets to say which evidence backs which assertion. Otherwise
    the plan's own assertions (summary + acceptance criteria) are bound to
    the plan's flat citation list, which is all the current model contract
    supports.
    """
    if plan.proposed_claims:
        return [
            (claim.text, _dedupe(claim.evidence_ids))
            for claim in plan.proposed_claims
            if claim.text.strip()
        ]
    sources: list[tuple[str, list[str]]] = []
    if plan.summary.strip():
        sources.append((plan.summary, _dedupe(plan.evidence_ids)))
    for criterion in plan.acceptance_criteria:
        if criterion.strip():
            sources.append((criterion, _dedupe(plan.evidence_ids)))
    return sources


def _resolve_claim(
    text: str,
    cited_ids: list[str],
    index: dict[str, EvidenceRecord],
    rejected: dict[str, str],
    weak_tokens: set[str],
    *,
    commit_ok: bool,
) -> tuple[list[str], list[GroundingWarning]]:
    """Return (matched evidence ids, warnings) for one claim."""
    matched: list[str] = []
    warnings: list[GroundingWarning] = []

    if not cited_ids:
        warnings.append(
            GroundingWarning(
                code="NO_EVIDENCE",
                message="claim cites no evidence and is recorded as a hypothesis",
                claim_text=text,
            )
        )
        return matched, warnings

    keywords = extract_keywords(text)
    for evidence_id in cited_ids:
        if evidence_id not in index:
            warnings.append(
                GroundingWarning(
                    code="UNKNOWN_EVIDENCE_ID",
                    message=(
                        f"claim cites {evidence_id!r}, which does not exist in this "
                        "run's evidence set"
                    ),
                    evidence_id=evidence_id,
                    claim_text=text,
                )
            )
            continue
        if evidence_id in rejected:
            # Already reported once at the record level; do not duplicate.
            continue
        if not commit_ok:
            continue
        if _relevant(keywords, index[evidence_id], weak_tokens):
            matched.append(evidence_id)
        else:
            warnings.append(
                GroundingWarning(
                    code="CLAIM_NOT_SUPPORTED_BY_EVIDENCE",
                    message=(
                        f"claim cites {evidence_id!r} "
                        f"({index[evidence_id].path}), but that evidence shares no "
                        "distinctive vocabulary with the claim"
                    ),
                    evidence_id=evidence_id,
                    claim_text=text,
                )
            )
    return matched, warnings


# -- structural checks --------------------------------------------------------


def _commit_matches(
    snapshot: RepositorySnapshot, workspace: Optional["RepoWorkspace"]
) -> bool:
    if workspace is None:
        return True  # cannot check; the report records that it was skipped
    try:
        return workspace.commit_sha == snapshot.commit_sha
    except Exception:
        return False


def _record_integrity(
    record: EvidenceRecord, workspace: "RepoWorkspace"
) -> Optional[str]:
    """Return a warning code when the record is structurally invalid."""
    try:
        if not workspace.exists(record.path):
            return "EVIDENCE_PATH_MISSING"
    except Exception:
        return "EVIDENCE_PATH_MISSING"

    if record.start_line is None and record.end_line is None:
        return None
    line_count = _line_count(workspace, record.path)
    if line_count is None:
        return None  # inconclusive: the file was too large to count safely
    start = record.start_line if record.start_line is not None else 1
    end = record.end_line if record.end_line is not None else start
    if start < 1 or end < start or end > line_count:
        return "EVIDENCE_LINE_RANGE_INVALID"
    return None


def _line_count(workspace: "RepoWorkspace", path: str) -> Optional[int]:
    try:
        text = workspace.read_text(path, max_chars=_LINE_COUNT_READ_CAP)
    except Exception:
        return None
    if len(text) >= _LINE_COUNT_READ_CAP:
        return None  # truncated: the count would be wrong
    return len(text.splitlines())


def _integrity_message(code: str, record: EvidenceRecord) -> str:
    if code == "EVIDENCE_PATH_MISSING":
        return f"evidence {record.id!r} cites {record.path!r}, which is not in the pinned snapshot"
    if code == "EVIDENCE_LINE_RANGE_INVALID":
        return (
            f"evidence {record.id!r} cites lines {record.start_line}-{record.end_line} "
            f"of {record.path!r}, which is outside that file"
        )
    return f"evidence {record.id!r} failed validation ({code})"


# -- lexical relevance --------------------------------------------------------


def _relevant(
    keywords: list[str], record: EvidenceRecord, weak_tokens: set[str]
) -> bool:
    """True when the claim's vocabulary genuinely appears in the evidence.

    Two conditions, both required:

    * the match must be on a *distinguishing* token — the repository's own
      name and tokens present in most records are excluded, because in
      psf/black almost every snippet says "black" and matching that proves
      nothing (this was found by an adversarial check against a real run);
    * at least **two** distinct keywords must match. One shared word is
      usually generic English ("project", "documented"), and treating a
      single shared word as proof is how a citation check becomes
      decorative again.

    Honest limitation: this is lexical, not semantic. It cannot tell that
    two differently-worded passages mean the same thing, so it will reject
    some genuinely-supported claims. Rejection is the safe direction — the
    claim is labelled a hypothesis, not silently accepted.
    """
    return len(_matching_keywords(keywords, record, weak_tokens)) >= 2


def _matching_keywords(
    keywords: list[str], record: EvidenceRecord, weak_tokens: set[str]
) -> list[str]:
    """Claim keywords that appear in the evidence, minus the weak ones."""
    haystack = f"{record.snippet}\n{record.path}".lower()
    tokens = set(_TOKEN_RE.findall(haystack))
    return [
        kw
        for kw in keywords
        if kw not in weak_tokens and _token_matches_any(kw, tokens)
    ]


def _non_discriminating_tokens(
    evidence: list[EvidenceRecord], snapshot: RepositorySnapshot
) -> set[str]:
    """Tokens that appear everywhere, so matching one proves nothing.

    The repository's own name is the important case: in psf/black, almost
    every snippet contains "black", so a claim that merely says "black"
    would otherwise look supported by any record at all. A token present in
    most records is equally useless as a discriminator.

    This is a blunt instrument and deliberately so: it can only make the
    validator more sceptical, never more credulous.
    """
    weak: set[str] = set()
    for value in (snapshot.name, snapshot.owner):
        if value:
            weak.update(_TOKEN_RE.findall(value.lower()))
    if not evidence:
        return weak

    counts: dict[str, int] = {}
    for record in evidence:
        for token in set(_TOKEN_RE.findall(f"{record.snippet}\n{record.path}".lower())):
            counts[token] = counts.get(token, 0) + 1
    threshold = max(2, (len(evidence) * 3 + 3) // 4)  # ~75% of records
    weak.update(token for token, hits in counts.items() if hits >= threshold)
    return weak


def _stem(token: str) -> str:
    """Strip one common English inflection.

    Deliberately minimal: it handles plurals and the -ing/-ed forms that
    dominate issue vocabulary, and leaves everything else alone. It is not
    a linguistic stemmer and does not pretend to be one.
    """
    for suffix, replacement in _SUFFIXES:
        if len(token) > len(suffix) + _MIN_STEM and token.endswith(suffix):
            return token[: -len(suffix)] + replacement
    return token


def _token_matches_any(keyword: str, tokens: Iterable[str]) -> bool:
    stem = _stem(keyword)
    for token in tokens:
        if keyword == token:
            return True
        other = _stem(token)
        if stem == other:
            return True
        # Silent-e / single-letter drift only: "exclud" ~ "exclude".
        shorter, longer = sorted((stem, other), key=len)
        if longer.startswith(shorter) and len(longer) - len(shorter) <= 1:
            return True
    return False


def _matched_keywords(
    text: str,
    matched_ids: list[str],
    index: dict[str, EvidenceRecord],
    weak_tokens: set[str],
) -> list[str]:
    """The distinguishing keywords shared by the claim and its evidence."""
    if not matched_ids:
        return []
    keywords = extract_keywords(text)
    found: list[str] = []
    for evidence_id in matched_ids:
        record = index.get(evidence_id)
        if record is None:
            continue
        for keyword in _matching_keywords(keywords, record, weak_tokens):
            if keyword not in found:
                found.append(keyword)
    return found


def _dedupe(values: Iterable[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for value in values:
        if value not in seen:
            seen.add(value)
            out.append(value)
    return out
