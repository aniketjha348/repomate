"""Read-only GitHub REST access with bounded rate-limit handling.

Unauthenticated access is limited to 60 requests/hour per source IP, so
every call is prepared for 403/429 with ``X-RateLimit-*`` headers: we wait
once (never longer than ``MAX_RATE_LIMIT_WAIT_SECONDS``) and retry a single
time before surfacing :class:`RateLimitedError` as a controlled failure.
"""

from __future__ import annotations

import time
from typing import Optional

from repomate_core.contracts import GitHubIssue
from repomate_core.repository.errors import GitHubAccessError, RateLimitedError
from repomate_core.repository.parsers import parse_issue, rate_limit_reset
from repomate_core.safety.network import GITHUB_HOST_ALLOWLIST, SafeHttpClient
from repomate_core.safety.url_guard import GitHubRef

GITHUB_API_BASE = "https://api.github.com"
MAX_RATE_LIMIT_WAIT_SECONDS = 30.0


def fetch_issue(
    ref: GitHubRef,
    *,
    token: Optional[str] = None,
    client: Optional[SafeHttpClient] = None,
) -> GitHubIssue:
    if ref.issue_number is None:
        raise GitHubAccessError("ref does not point at an issue")

    url = f"{GITHUB_API_BASE}/repos/{ref.owner}/{ref.repo}/issues/{ref.issue_number}"
    headers = {
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    if token:
        headers["Authorization"] = f"Bearer {token}"

    owns_client = client is None
    if client is None:
        client = SafeHttpClient(allowed_hosts=GITHUB_HOST_ALLOWLIST)

    try:
        for attempt in range(2):
            try:
                response = client.get(url, headers=headers)
            except Exception as exc:  # httpx transport / DNS / policy errors
                raise GitHubAccessError(f"cannot reach GitHub API: {exc}") from exc

            if response.status_code == 200:
                return parse_issue(response.json(), ref)

            if response.status_code in (403, 429) and attempt == 0:
                reset_at = rate_limit_reset(response.headers)
                remaining = response.headers.get("x-ratelimit-remaining", "1")
                if remaining == "0" and reset_at is not None:
                    wait = min(reset_at - time.time(), MAX_RATE_LIMIT_WAIT_SECONDS)
                    if wait > 0:
                        time.sleep(wait)
                        continue
                raise RateLimitedError(
                    "GitHub API rate limit exhausted", reset_at=reset_at
                )

            if response.status_code == 404:
                raise GitHubAccessError(
                    f"issue not found: {ref.owner}/{ref.repo}#{ref.issue_number}"
                )
            if response.status_code in (401, 403):
                raise GitHubAccessError(
                    "GitHub refused the request (bad token or restricted resource)"
                )
            raise GitHubAccessError(
                f"unexpected GitHub API status {response.status_code}"
            )
        raise GitHubAccessError("unreachable")
    finally:
        if owns_client:
            client.close()
