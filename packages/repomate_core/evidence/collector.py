"""Keyword-driven evidence retrieval.

No plan is allowed without evidence: the issue itself is recorded, then
documentation and source files are scored by keyword coverage and the top
files are cited with bounded snippets and exact line ranges. An empty
result forces ``NEED_MORE_INFO`` upstream.
"""

from __future__ import annotations

from pathlib import PurePosixPath
from typing import Optional

from repomate_core.contracts import (
    EvidenceKind,
    EvidenceRecord,
    GitHubIssue,
    RepositorySnapshot,
)
from repomate_core.evidence.keywords import extract_keywords
from repomate_core.evidence.windows import best_window
from repomate_core.repository.workspace import RepoWorkspace

_MAX_RECORDS = 8
_SNIPPET_MAX_CHARS = 1800

_READABLE_EXTENSIONS = {
    ".md", ".rst", ".txt", ".py", ".js", ".ts", ".tsx", ".jsx", ".go",
    ".rs", ".java", ".rb", ".c", ".h", ".cpp", ".hpp", ".cs", ".php",
    ".sh", ".toml", ".yaml", ".yml", ".json", ".cfg", ".ini",
}

_SKIP_DIRS = {".git", ".github", "node_modules", "vendor", "dist", "build"}


def collect_evidence(
    ws: RepoWorkspace,
    snapshot: RepositorySnapshot,
    task_text: str,
    issue: Optional[GitHubIssue] = None,
    *,
    max_records: int = _MAX_RECORDS,
) -> list[EvidenceRecord]:
    records: list[EvidenceRecord] = []
    if issue is not None:
        records.append(_issue_record(issue))
        max_records -= 1
    if max_records <= 0:
        return records

    keywords = extract_keywords(
        task_text, issue.title if issue else None, issue.body if issue else None
    )
    if not keywords:
        return records

    for _score, path, kind in _scored_files(ws, snapshot, keywords)[:max_records]:
        record = _file_record(ws, path, kind, keywords)
        if record is not None:
            records.append(record)

    for seq, record in enumerate(records, start=1):
        record.id = f"ev{seq}"
    return records


def _issue_record(issue: GitHubIssue) -> EvidenceRecord:
    body_excerpt = (issue.body or "").strip()[:1500]
    return EvidenceRecord(
        id="",
        kind=EvidenceKind.ISSUE,
        path=f"issue#{issue.number}",
        snippet=f"{issue.title}\n\n{body_excerpt}".strip()[:_SNIPPET_MAX_CHARS],
        rationale="the GitHub issue this contribution addresses",
    )


def _scored_files(ws: RepoWorkspace, snapshot: RepositorySnapshot, keywords: list[str]):
    """Rank readable files by weighted keyword coverage.

    Matches count both in file content and in the path itself (tokenized
    segments), so an issue naming "slugify" surfaces ``slugify.py`` even
    when the body never mentions it.
    """
    scored = []
    for f in ws.ls_files():
        path = PurePosixPath(f)
        if path.suffix.lower() not in _READABLE_EXTENSIONS:
            continue
        if set(path.parts) & _SKIP_DIRS:
            continue
        try:
            text = ws.read_text(f, max_chars=250_000)
        except Exception:
            continue
        content_hits = sum(1 for kw in keywords if kw in text.lower())
        path_hits = sum(1 for kw in keywords if kw in path.stem.lower())
        if content_hits == 0 and path_hits == 0:
            continue
        weight = _file_weight(path, snapshot)
        scored.append(((content_hits + 0.8 * path_hits) * weight, f, _file_kind(path)))
    scored.sort(key=lambda item: (-item[0], item[1]))
    return scored


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
    ws: RepoWorkspace, path: str, kind: EvidenceKind, keywords: list[str]
) -> Optional[EvidenceRecord]:
    snippet, start, end, matched = best_window(ws, path, keywords)
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
