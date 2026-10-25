"""Keyword extraction from task/issue text."""

from __future__ import annotations

import re
from typing import Optional

_MAX_KEYWORDS = 12

_STOPWORDS = {
    "the", "a", "an", "and", "or", "but", "for", "with", "without", "into",
    "this", "that", "these", "those", "from", "to", "of", "in", "on", "at",
    "is", "are", "was", "were", "be", "been", "being", "it", "its", "as",
    "by", "not", "no", "yes", "we", "you", "they", "i", "should", "would",
    "could", "can", "will", "shall", "may", "might", "must", "do", "does",
    "did", "have", "has", "had", "add", "adds", "make", "makes", "use",
    "using", "when", "what", "which", "who", "how", "why", "please",
    "issue", "issues", "repository", "repo", "code", "file", "files",
    "section", "documentation", "document", "documenting", "readme",
}

_TOKEN_RE = re.compile(r"[A-Za-z][A-Za-z0-9_-]{2,}")


def extract_keywords(*texts: Optional[str], limit: int = _MAX_KEYWORDS) -> list[str]:
    """Ordered, de-duplicated significant words (lowercased)."""
    words: list[str] = []
    for text in texts:
        if not text:
            continue
        for token in _TOKEN_RE.findall(text.lower()):
            if token not in _STOPWORDS and token not in words:
                words.append(token)
    return words[:limit]
