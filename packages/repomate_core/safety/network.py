"""SSRF-hardened HTTP access for outbound calls.

Every URL fetched on behalf of a user goes through :class:`SafeHttpClient`:

- https scheme only
- DNS-resolved addresses must be public — loopback, private, link-local,
  CGNAT, reserved and multicast ranges are rejected before connecting
- redirects are followed manually (max 3 hops) and every hop is
  re-validated against a GitHub host allowlist
- response bodies are size-capped
"""

from __future__ import annotations

import ipaddress
import socket
from typing import Any, Optional
from urllib.parse import urljoin, urlsplit

import httpx

_BLOCKED_V4 = [
    ipaddress.ip_network(n)
    for n in (
        "0.0.0.0/8", "10.0.0.0/8", "100.64.0.0/10", "127.0.0.0/8",
        "169.254.0.0/16", "172.16.0.0/12", "192.0.0.0/24", "192.0.2.0/24",
        "192.88.99.0/24", "192.168.0.0/16", "198.18.0.0/15",
        "198.51.100.0/24", "203.0.113.0/24", "224.0.0.0/4",
        "233.252.0.0/24", "240.0.0.0/4",
    )
]
_BLOCKED_V6 = [
    ipaddress.ip_network(n)
    for n in (
        "::/128", "::1/128",
        "64:ff9b::/96",  # NAT64 well-known prefix: can embed private IPv4
        "fc00::/7", "fe80::/10", "ff00::/8",
    )
]

# Redirect targets reachable from api.github.com / github.com responses.
GITHUB_HOST_ALLOWLIST = {
    "github.com",
    "www.github.com",
    "api.github.com",
    "codeload.github.com",
    "objects.githubusercontent.com",
    "raw.githubusercontent.com",
    "api.github.com.",
}


class NetworkSafetyError(RuntimeError):
    """Raised when a fetch violates the network policy."""


def assert_public_https_url(url: str, *, allow_hosts: Optional[set[str]] = None) -> None:
    parts = urlsplit(url)
    if parts.scheme != "https":
        raise NetworkSafetyError(f"non-https URL refused: {url!r}")
    host = (parts.hostname or "").lower()
    if not host:
        raise NetworkSafetyError("URL has no host")
    if allow_hosts is not None and host not in allow_hosts:
        raise NetworkSafetyError(f"host {host!r} is not in the allowlist")
    try:
        infos = socket.getaddrinfo(host, parts.port or 443, proto=socket.IPPROTO_TCP)
    except socket.gaierror as exc:
        raise NetworkSafetyError(f"cannot resolve host {host!r}: {exc}") from exc
    for info in infos:
        _refuse_non_public(host, info[4][0])


def _refuse_non_public(host: str, raw_addr: str) -> None:
    try:
        addr = ipaddress.ip_address(raw_addr.split("%", 1)[0])
    except ValueError as exc:
        raise NetworkSafetyError(
            f"host {host!r} resolved to an unparseable address {raw_addr!r}; refusing"
        ) from exc
    # Judge IPv4-mapped IPv6 (``::ffff:127.0.0.1``) as its IPv4 target; some
    # Python versions classify the mapped prefix itself as public.
    if isinstance(addr, ipaddress.IPv6Address) and addr.ipv4_mapped is not None:
        addr = addr.ipv4_mapped
    blocked = _BLOCKED_V6 if addr.version == 6 else _BLOCKED_V4
    if not addr.is_global or any(addr in net for net in blocked):
        raise NetworkSafetyError(
            f"host {host!r} resolves to a non-public address {addr}; refusing"
        )


class SafeHttpClient:
    """A small GET client with redirect, address and size controls."""

    def __init__(
        self,
        *,
        timeout: float = 30.0,
        max_redirects: int = 3,
        max_body_bytes: int = 20 * 1024 * 1024,
        user_agent: str = "repomate/0.1 (+https://github.com/)",
        allowed_hosts: Optional[set[str]] = None,
    ) -> None:
        self._timeout = timeout
        self._max_redirects = max_redirects
        self._max_body_bytes = max_body_bytes
        self._user_agent = user_agent
        self._allowed_hosts = allowed_hosts if allowed_hosts is not None else set(GITHUB_HOST_ALLOWLIST)
        self._client = httpx.Client(timeout=timeout, follow_redirects=False)

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> "SafeHttpClient":
        return self

    def __exit__(self, *exc_info: Any) -> None:
        self.close()

    def get(
        self,
        url: str,
        *,
        headers: Optional[dict[str, str]] = None,
        allowed_hosts: Optional[set[str]] = None,
    ) -> httpx.Response:
        """GET ``url`` following at most ``max_redirects`` validated hops.

        ``allowed_hosts`` narrows (never widens) the constructor allowlist —
        useful for operator-configured endpoints such as the model gateway,
        which pass an explicit host set instead of the GitHub default.
        """
        hosts = self._allowed_hosts
        if allowed_hosts is not None:
            hosts = set(allowed_hosts)

        current = url
        for _hop in range(self._max_redirects + 1):
            assert_public_https_url(current, allow_hosts=hosts)
            request_headers = {"User-Agent": self._user_agent}
            if headers:
                request_headers.update(headers)
            response = self._client.get(current, headers=request_headers)
            if response.is_redirect:
                location = response.headers.get("location")
                if not location:
                    raise NetworkSafetyError("redirect without a Location header")
                current = urljoin(current, location)
                continue
            if len(response.content) > self._max_body_bytes:
                raise NetworkSafetyError("response body exceeded the size cap")
            return response
        raise NetworkSafetyError(f"too many redirects (> {self._max_redirects})")
