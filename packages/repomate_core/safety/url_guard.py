"""Validation of user-supplied GitHub URLs.

MVP policy (mirrored in docs/security.md):

- ``https://`` scheme only, host must be exactly ``github.com``
- no userinfo, no explicit port, no fragment
- path must be ``/{owner}/{repo}`` or ``/{owner}/{repo}/issues/{number}``
- ``.git`` suffix is tolerated and stripped
- pull-request URLs are rejected as unsupported input (MVP scope)
- tracking query parameters (``utm_*`` etc.) are stripped; any other
  query parameter is rejected
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from urllib.parse import parse_qsl, urlsplit, urlunsplit

_REPO_SEGMENT = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9._-]{0,98}[A-Za-z0-9])?$")
_TRACKING_PREFIXES = ("utm_", "ref_", "fbclid", "gclid")


class UnsafeInputError(ValueError):
    """Raised when a URL violates the input policy."""


@dataclass(frozen=True)
class GitHubRef:
    owner: str
    repo: str
    issue_number: int | None
    canonical_url: str
    repo_url: str

    @property
    def slug(self) -> str:
        return f"{self.owner}/{self.repo}"


def parse_github_url(raw: str) -> GitHubRef:
    if not isinstance(raw, str) or not raw.strip():
        raise UnsafeInputError("URL must be a non-empty string")

    parts = urlsplit(raw.strip())
    if parts.scheme != "https":
        raise UnsafeInputError("only https:// URLs are accepted")
    if parts.fragment:
        raise UnsafeInputError("URLs with a fragment are not accepted")
    if parts.username or parts.password:
        raise UnsafeInputError("URLs with credentials are not accepted")
    if parts.port is not None:
        raise UnsafeInputError("URLs with an explicit port are not accepted")
    host = (parts.hostname or "").lower()
    if host != "github.com":
        raise UnsafeInputError(f"only github.com URLs are accepted (got {host!r})")

    if parts.query:
        for key, _value in parse_qsl(parts.query, keep_blank_values=True):
            if not key.lower().startswith(_TRACKING_PREFIXES):
                raise UnsafeInputError(f"unsupported query parameter {key!r}")

    segments = [s for s in parts.path.split("/") if s]
    if not (2 <= len(segments) <= 4):
        raise UnsafeInputError(
            "expected https://github.com/{owner}/{repo} or .../issues/{number}"
        )

    owner, repo = segments[0], segments[1]
    if repo.endswith(".git"):
        repo = repo[: -len(".git")]
    for label, value in (("owner", owner), ("repo", repo)):
        if not _REPO_SEGMENT.match(value):
            raise UnsafeInputError(f"invalid {label} segment {value!r}")

    issue_number: int | None = None
    if len(segments) > 2:
        kind = segments[2].lower()
        if kind == "pull":
            raise UnsafeInputError(
                "pull-request URLs are not supported yet; use an issue URL"
            )
        if kind != "issues" or len(segments) != 4:
            raise UnsafeInputError(
                "only /{owner}/{repo} or /{owner}/{repo}/issues/{number} paths are accepted"
            )
        if not segments[3].isdigit() or int(segments[3]) < 1:
            raise UnsafeInputError("issue number must be a positive integer")
        issue_number = int(segments[3])

    repo_url = urlunsplit(("https", "github.com", f"/{owner}/{repo}", "", ""))
    canonical = (
        f"{repo_url}/issues/{issue_number}" if issue_number is not None else repo_url
    )
    return GitHubRef(
        owner=owner, repo=repo, issue_number=issue_number,
        canonical_url=canonical, repo_url=repo_url,
    )
