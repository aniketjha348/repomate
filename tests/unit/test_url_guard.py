"""Unit tests for GitHub URL input validation."""

import pytest

from repomate_core.safety.url_guard import UnsafeInputError, parse_github_url


class TestAccepted:
    def test_issue_url_with_tracking_query(self):
        ref = parse_github_url(
            "https://github.com/owner/repository/issues/123?utm_source=chatgpt.com"
        )
        assert (ref.owner, ref.repo, ref.issue_number) == ("owner", "repository", 123)
        assert ref.canonical_url == "https://github.com/owner/repository/issues/123"

    def test_repo_url(self):
        ref = parse_github_url("https://github.com/psf/black")
        assert ref.issue_number is None
        assert ref.repo_url == "https://github.com/psf/black"

    def test_git_suffix_stripped(self):
        ref = parse_github_url("https://github.com/psf/black.git")
        assert ref.repo == "black"

    def test_trailing_slash(self):
        ref = parse_github_url("https://github.com/psf/black/")
        assert (ref.owner, ref.repo) == ("psf", "black")


class TestRejected:
    @pytest.mark.parametrize(
        "url",
        [
            "http://github.com/owner/repo",                       # not https
            "https://evil.com/owner/repo",                        # wrong host
            "https://api.github.com/repos/owner/repo",            # api host, wrong shape
            "https://user:pass@github.com/owner/repo",            # credentials
            "https://github.com:8443/owner/repo",                 # explicit port
            "https://github.com/owner/repo/issues/123#discussion",# fragment
            "https://github.com/owner/repo/pull/9",               # PR unsupported
            "https://github.com/owner",                           # missing repo
            "https://github.com/owner/repo/issues/abc",           # non-numeric issue
            "https://github.com/owner/repo/issues/0",             # zero issue
            "https://github.com/owner/repo/issues/1/extra",       # extra path segment
            "https://github.com/owner/repo?token=abc123",         # non-tracking query
            "not a url",
            "",
        ],
    )
    def test_rejected(self, url):
        with pytest.raises(UnsafeInputError):
            parse_github_url(url)
