"""Payload/header parsing helpers for the GitHub REST client."""

from __future__ import annotations

from typing import Optional

from repomate_core.contracts import GitHubIssue
from repomate_core.repository.errors import GitHubAccessError
from repomate_core.safety.url_guard import GitHubRef


def rate_limit_reset(headers) -> Optional[float]:
    raw = headers.get("x-ratelimit-reset")
    if raw is None or not raw.isdigit():
        return None
    return float(raw)


def parse_issue(payload: dict, ref: GitHubRef) -> GitHubIssue:
    # The issues API returns pull requests for /pull/N; we never request
    # those, but guard anyway so a PR payload is never mistaken for an issue.
    if "pull_request" in payload:
        raise GitHubAccessError("URL points at a pull request, not an issue")
    return GitHubIssue(
        url=payload.get("html_url") or ref.canonical_url,
        number=int(payload.get("number") or ref.issue_number or 0),
        title=payload.get("title") or "",
        body=payload.get("body") or "",
        state=payload.get("state") or "open",
        labels=[label.get("name", "") for label in payload.get("labels", [])],
    )
