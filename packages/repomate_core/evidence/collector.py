"""Keyword-driven evidence retrieval with explicit, reportable budgets.

No plan is allowed without evidence: the issue itself is recorded, then
documentation and source files are scored by keyword coverage and the top
files are cited with bounded snippets and exact line ranges. An empty
result forces ``NEED_MORE_INFO`` upstream.

Retrieval is bounded by files examined, bytes per file, cumulative bytes,
matching search results and wall-clock time. When any limit is reached the
report is ``PARTIAL`` and names the unexamined work; it never describes a
truncated scan as complete repository analysis.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from pathlib import PurePosixPath
from typing import Optional

from repomate_core.contracts import (
    EvidenceKind,
    EvidenceRecord,
    GitHubIssue,
    RepositorySnapshot,
    RetrievalLimit,
    RetrievalLimitHit,
    RetrievalLimits,
    RetrievalReport,
    RetrievalStatus,
)
from repomate_core.evidence.keywords import extract_keywords
from repomate_core.evidence.windows import best_window_from_text
from repomate_core.repository.workspace import RepoWorkspace

_MAX_RECORDS = 8

_READABLE_EXTENSIONS = {
    ".md", ".rst", ".txt", ".py", ".js", ".ts", ".tsx", ".jsx", ".go",
    ".rs", ".java", ".rb", ".c", ".h", ".cpp", ".hpp", ".cs", ".php",
    ".sh", ".toml", ".yaml", ".yml", ".json", ".cfg", ".ini",
}

_SKIP_DIRS = {".git", ".github", "node_modules", "vendor", "dist", "build"}


@dataclass
class RetrievalOutcome:
    """Evidence records plus the proof of how much of the repo was searched."""

    records: list[EvidenceRecord]
    report: RetrievalReport


@dataclass
class _Candidate:
    score: float
    path: str
    kind: EvidenceKind
    text: str


def collect_evidence(
    ws: RepoWorkspace,
    snapshot: RepositorySnapshot,
    task_text: str,
    issue: Optional[GitHubIssue] = None,
    *,
    max_records: int = _MAX_RECORDS,
    limits: Optional[RetrievalLimits] = None,
) -> list[EvidenceRecord]:
    """Backwards-compatible list-only view of :func:`collect_evidence_with_report`."""
    return collect_evidence_with_report(
        ws,
        snapshot,
        task_text,
        issue,
        max_records=max_records,
        limits=limits,
    ).records


def collect_evidence_with_report(
    ws: RepoWorkspace,
    snapshot: RepositorySnapshot,
    task_text: str,
    issue: Optional[GitHubIssue] = None,
    *,
    max_records: int = _MAX_RECORDS,
    limits: Optional[RetrievalLimits] = None,
) -> RetrievalOutcome:
    started = time.monotonic()
    active = limits or RetrievalLimits()
    records: list[EvidenceRecord] = []
    if issue is not None:
        records.append(_issue_record(issue))
        max_records -= 1

    keywords = extract_keywords(
        task_text, issue.title if issue else None, issue.body if issue else None
    )
    files = ws.ls_files()
    eligible = _eligible_files(files)

    examined = 0
    bytes_read = 0
    candidates: list[_Candidate] = []
    truncated_files: list[tuple[str, int, int]] = []
    max_files_hit = False
    search_results_hit: Optional[str] = None
    total_bytes_hit: Optional[tuple[Optional[str], int]] = None
    seconds_hit: Optional[float] = None

    if keywords and max_records > 0:
        for path, pure in eligible:
            if examined >= active.max_files:
                max_files_hit = True
                break

            elapsed = time.monotonic() - started
            if elapsed >= active.max_seconds:
                seconds_hit = elapsed
                break

            remaining_total = active.max_total_bytes - bytes_read
            if remaining_total <= 0:
                total_bytes_hit = (None, 0)
                break

            read_cap = min(active.max_bytes_per_file, remaining_total)
            try:
                text, size, truncated = ws.read_text_bounded(path, max_bytes=read_cap)
            except Exception:
                # An unreadable tracked file is not a budget hit; keep the
                # scan moving and let the eligible/examined counts show it.
                examined += 1
                continue

            examined += 1
            bytes_read += min(size, read_cap)

            clipped_by_total: Optional[int] = None
            if truncated:
                if read_cap == active.max_bytes_per_file:
                    truncated_files.append((path, size, read_cap))
                else:
                    clipped_by_total = size - read_cap

            content_hits = sum(1 for kw in keywords if kw in text.lower())
            path_hits = sum(1 for kw in keywords if kw in pure.stem.lower())
            if content_hits or path_hits:
                if len(candidates) >= active.max_search_results:
                    search_results_hit = path
                    break
                candidates.append(
                    _Candidate(
                        score=(content_hits + 0.8 * path_hits)
                        * _file_weight(pure, snapshot),
                        path=path,
                        kind=_file_kind(pure),
                        text=text,
                    )
                )

            if clipped_by_total is not None:
                total_bytes_hit = (path, clipped_by_total)
                break

    candidates.sort(key=lambda item: (-item.score, item.path))
    for candidate in candidates[: max(0, max_records)]:
        record = _file_record(
            candidate.path, candidate.kind, keywords, candidate.text
        )
        if record is not None:
            records.append(record)

    for seq, record in enumerate(records, start=1):
        record.id = f"ev{seq}"

    hits = _limit_hits(
        active,
        eligible_count=len(eligible),
        examined=examined,
        bytes_read=bytes_read,
        truncated_files=truncated_files,
        max_files_hit=max_files_hit,
        search_results_hit=search_results_hit,
        total_bytes_hit=total_bytes_hit,
        seconds_hit=seconds_hit,
    )
    status = RetrievalStatus.PARTIAL if hits else RetrievalStatus.COMPLETE
    elapsed_ms = max(0, int((time.monotonic() - started) * 1000))
    report = RetrievalReport(
        status=status,
        limits=active,
        files_total=len(files),
        files_eligible=len(eligible),
        files_examined=examined,
        bytes_read=bytes_read,
        search_results=len(candidates),
        evidence_records=len(records),
        elapsed_ms=elapsed_ms,
        limit_hits=hits,
        summary=_summary(
            status,
            active,
            files_total=len(files),
            files_eligible=len(eligible),
            examined=examined,
            bytes_read=bytes_read,
            search_results=len(candidates),
            hits=hits,
            search_requested=bool(keywords) and max_records > 0,
        ),
    )
    return RetrievalOutcome(records=records, report=report)


def _eligible_files(files: list[str]) -> list[tuple[str, PurePosixPath]]:
    eligible: list[tuple[str, PurePosixPath]] = []
    for raw in files:
        path = PurePosixPath(raw)
        if path.suffix.lower() not in _READABLE_EXTENSIONS:
            continue
        if set(path.parts) & _SKIP_DIRS:
            continue
        eligible.append((raw, path))
    return eligible


def _limit_hits(
    limits: RetrievalLimits,
    *,
    eligible_count: int,
    examined: int,
    bytes_read: int,
    truncated_files: list[tuple[str, int, int]],
    max_files_hit: bool,
    search_results_hit: Optional[str],
    total_bytes_hit: Optional[tuple[Optional[str], int]],
    seconds_hit: Optional[float],
) -> list[RetrievalLimitHit]:
    """Build one deterministic hit per exhausted budget, in a fixed order."""
    hits: list[RetrievalLimitHit] = []
    remaining = max(0, eligible_count - examined)

    if max_files_hit:
        hits.append(
            RetrievalLimitHit(
                limit=RetrievalLimit.MAX_FILES,
                allowed=limits.max_files,
                observed=eligible_count,
                remaining_work=(
                    f"{remaining} eligible file(s) were not examined because the "
                    f"{limits.max_files}-file retrieval cap was reached."
                ),
            )
        )

    if truncated_files:
        total_unread = sum(size - cap for _path, size, cap in truncated_files)
        largest_path, largest_size, cap = max(
            truncated_files, key=lambda item: (item[1] - item[2], item[0])
        )
        hits.append(
            RetrievalLimitHit(
                limit=RetrievalLimit.MAX_BYTES_PER_FILE,
                allowed=cap,
                observed=largest_size,
                remaining_work=(
                    f"{len(truncated_files)} file(s) were truncated at {cap} "
                    f"byte(s); {total_unread} byte(s) were not read, including "
                    f"{largest_size - cap} trailing byte(s) of {largest_path}."
                ),
            )
        )

    if total_bytes_hit is not None:
        clipped_path, clipped_bytes = total_bytes_hit
        if clipped_path is not None:
            detail = (
                f"{clipped_bytes} trailing byte(s) of {clipped_path} were not "
                f"read, and {remaining} eligible file(s) were not examined"
            )
        else:
            detail = f"{remaining} eligible file(s) were not examined"
        hits.append(
            RetrievalLimitHit(
                limit=RetrievalLimit.MAX_TOTAL_BYTES,
                allowed=limits.max_total_bytes,
                observed=bytes_read,
                remaining_work=(
                    f"{detail} because the {limits.max_total_bytes}-byte total "
                    "retrieval budget was exhausted."
                ),
            )
        )

    if search_results_hit is not None:
        hits.append(
            RetrievalLimitHit(
                limit=RetrievalLimit.MAX_SEARCH_RESULTS,
                allowed=limits.max_search_results,
                observed=limits.max_search_results + 1,
                remaining_work=(
                    f"{search_results_hit} matched but was not retained, and any "
                    f"lower-ranked matches were not considered; {remaining} "
                    "eligible file(s) were not examined because the "
                    f"{limits.max_search_results}-result search cap was reached."
                ),
            )
        )

    if seconds_hit is not None:
        hits.append(
            RetrievalLimitHit(
                limit=RetrievalLimit.MAX_SECONDS,
                allowed=limits.max_seconds,
                observed=round(seconds_hit, 3),
                remaining_work=(
                    f"{remaining} eligible file(s) were not examined because the "
                    f"{limits.max_seconds:g}s retrieval budget was exhausted."
                ),
            )
        )

    return hits


def _summary(
    status: RetrievalStatus,
    limits: RetrievalLimits,
    *,
    files_total: int,
    files_eligible: int,
    examined: int,
    bytes_read: int,
    search_results: int,
    hits: list[RetrievalLimitHit],
    search_requested: bool,
) -> str:
    if not search_requested:
        prefix = (
            "Retrieval is COMPLETE: the task yielded no searchable keywords or "
            "the evidence budget was already filled, so no repository file "
            "search was required."
        )
    else:
        prefix = (
            f"Retrieval is {status.value}: examined {examined} of "
            f"{files_eligible} eligible file(s) from {files_total} tracked "
            f"file(s), read {bytes_read} byte(s), and retained "
            f"{search_results} matching file(s)."
        )

    if status is RetrievalStatus.COMPLETE:
        return f"{prefix} No retrieval limit was reached."

    remaining = max(0, files_eligible - examined)
    if remaining:
        prefix += f" {remaining} eligible file(s) were not examined."
    prefix += (
        " Limits reached: "
        + ", ".join(hit.limit.value for hit in hits)
        + ". This analysis does not cover the whole repository."
    )
    return prefix


def _issue_record(issue: GitHubIssue) -> EvidenceRecord:
    body_excerpt = (issue.body or "").strip()[:1500]
    return EvidenceRecord(
        id="",
        kind=EvidenceKind.ISSUE,
        path=f"issue#{issue.number}",
        snippet=f"{issue.title}\n\n{body_excerpt}".strip()[:1800],
        rationale="the GitHub issue this contribution addresses",
    )


def _file_weight(path: PurePosixPath, snapshot: RepositorySnapshot) -> float:
    if path.suffix.lower() in {".md", ".rst"} or "docs" in path.parts:
        return 1.5
    if "test" in path.name.lower() or "tests" in path.parts:
        return 1.2
    return 1.0


def _file_kind(path: PurePosixPath) -> EvidenceKind:
    if "test" in path.name.lower() or "tests" in path.parts:
        return EvidenceKind.TEST
    if path.suffix.lower() in {".md", ".rst"} or "docs" in path.parts:
        return EvidenceKind.DOC
    return EvidenceKind.SOURCE


def _file_record(
    path: str, kind: EvidenceKind, keywords: list[str], text: str
) -> Optional[EvidenceRecord]:
    snippet, start, end, matched = best_window_from_text(text, keywords)
    if snippet is None:
        return None
    return EvidenceRecord(
        id="",
        kind=kind,
        path=path,
        start_line=start,
        end_line=end,
        snippet=snippet,
        rationale=f"matches task keywords: {', '.join(matched[:5])}",
    )
