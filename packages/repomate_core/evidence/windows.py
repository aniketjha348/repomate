"""Best-match line-window extraction for evidence snippets.

Given a file's lines and the task keywords, find the window with the
highest keyword density and return it with exact 1-based line ranges.
"""

from __future__ import annotations

from typing import Optional

from repomate_core.repository.workspace import RepoWorkspace

_SNIPPET_WINDOW = 12
_SNIPPET_MAX_CHARS = 1800


def best_window(
    ws: RepoWorkspace, path: str, keywords: list[str]
) -> tuple[Optional[str], Optional[int], Optional[int], list[str]]:
    """Returns (snippet, start_line, end_line, matched_keywords)."""
    try:
        text = ws.read_text(path, max_chars=250_000)
    except Exception:
        return None, None, None, []
    return best_window_from_text(text, keywords)


def best_window_from_text(
    text: str, keywords: list[str]
) -> tuple[Optional[str], Optional[int], Optional[int], list[str]]:
    """Same as :func:`best_window` for content already in memory.

    Retrieval reads each file once under its byte budget; snippet extraction
    must not perform a second unbounded read.
    """
    lines = text.splitlines()
    if not lines:
        return None, None, None, []

    hits = _line_hits(lines, keywords)
    if not hits:
        return None, None, None, []

    best_start = hits[0]
    best_density = -1.0
    for anchor in hits:
        start = max(0, anchor - 2)
        density = _density(hits, start)
        if density > best_density:
            best_density, best_start = density, start

    selected = lines[best_start : best_start + _SNIPPET_WINDOW]
    snippet = "\n".join(selected).strip()[:_SNIPPET_MAX_CHARS]
    matched = sorted(
        {kw for line in selected for kw in keywords if kw in line.lower()},
        key=keywords.index,
    )
    return snippet, best_start + 1, best_start + len(selected), matched


def _line_hits(lines: list[str], keywords: list[str]) -> list[int]:
    return [
        i for i, line in enumerate(lines)
        if any(kw in line.lower() for kw in keywords)
    ]


def _density(hits: list[int], start: int) -> float:
    window = _SNIPPET_WINDOW
    in_window = sum(1 for h in hits if start <= h < start + window)
    return in_window / (window + (2 if start > 0 else 0))
