"""Unit tests for the SSRF network guard (no real fetches)."""

import pytest

from repomate_core.safety.network import NetworkSafetyError, assert_public_https_url


@pytest.mark.parametrize(
    "url",
    [
        "https://127.0.0.1/repo",
        "https://localhost/repo",
        "https://10.0.0.5/repo",
        "https://169.254.169.254/latest/meta-data",   # cloud metadata endpoint
        "https://192.168.1.10/repo",
        "https://172.16.0.9/repo",
        "https://[::1]/repo",
        "https://100.64.0.1/repo",                    # CGNAT
        "https://198.18.0.5/repo",                    # benchmark range
        "https://240.0.0.1/repo",                     # reserved
    ],
)
def test_non_public_hosts_rejected(url):
    with pytest.raises(NetworkSafetyError):
        assert_public_https_url(url, allow_hosts=None)


def test_http_scheme_rejected():
    with pytest.raises(NetworkSafetyError):
        assert_public_https_url("http://github.com/owner/repo")


def test_host_outside_allowlist_rejected():
    with pytest.raises(NetworkSafetyError):
        assert_public_https_url("https://example.invalid/x", allow_hosts={"github.com"})


def test_unresolvable_host_rejected():
    with pytest.raises(NetworkSafetyError):
        assert_public_https_url(
            "https://this-host-does-not-exist.invalid/x", allow_hosts={"this-host-does-not-exist.invalid"}
        )
