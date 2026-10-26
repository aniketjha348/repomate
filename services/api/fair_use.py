"""Fair-use admission control for run submission.

Three independent controls protect the service:

1. **Per-client request rate** — an in-process sliding window. The client is
   the socket peer unless that peer is an explicitly configured trusted proxy,
   in which case the right-most untrusted ``X-Forwarded-For`` hop is used.
2. **Concurrent runs** — the number of persisted ``PENDING``/``RUNNING`` runs
   plus short in-process reservations made between the admission check and
   saving the new run record.
3. **Run budgets** — max runtime, model calls/tokens, tool retrieval, and
   cancellation are enforced by the pipeline itself (see
   :mod:`repomate_core.orchestration.context`), not here.

Honest limitation: the rate-limit window and the reservations are per API
process. With multiple replicas the shared store still caps concurrent runs
approximately, but each replica applies its own request window and two
replicas can admit at the same instant. The deployment docs say so.
"""

from __future__ import annotations

import ipaddress
import math
import threading
import time
from collections import deque
from contextlib import contextmanager
from typing import Deque, Iterator, Optional, Sequence

from fastapi import Request

from services.api.config import Settings

IPAddress = ipaddress.IPv4Address | ipaddress.IPv6Address
IPNetwork = ipaddress.IPv4Network | ipaddress.IPv6Network

# Bound limiter memory: prune stale client buckets when the table gets large.
_MAX_TRACKED_CLIENTS = 4096


class FairUseError(Exception):
    """An admission control refused a run submission."""

    def __init__(self, message: str, *, retry_after: float) -> None:
        super().__init__(message)
        self.retry_after = max(1, int(math.ceil(retry_after)))


class SlidingWindowLimiter:
    """Thread-safe per-key sliding-window request limiter."""

    def __init__(self) -> None:
        self._hits: dict[str, Deque[float]] = {}
        self._lock = threading.Lock()

    def hit(self, key: str, *, limit: int, window_seconds: float) -> float:
        """Record one request.

        Returns ``0.0`` when admitted, or the number of seconds until the
        oldest hit leaves the window when the limit is exhausted. A rejected
        request does not consume a slot (so retries cannot extend the ban).
        """
        now = time.monotonic()
        cutoff = now - window_seconds
        with self._lock:
            bucket = self._hits.get(key)
            if bucket is None:
                bucket = deque()
                self._hits[key] = bucket
            while bucket and bucket[0] <= cutoff:
                bucket.popleft()
            if len(bucket) >= limit:
                return max(0.0, bucket[0] + window_seconds - now)
            bucket.append(now)
            self._prune(cutoff)
            return 0.0

    def active_clients(self) -> int:
        with self._lock:
            return len(self._hits)

    def reset(self) -> None:
        with self._lock:
            self._hits.clear()

    def _prune(self, cutoff: float) -> None:
        if len(self._hits) <= _MAX_TRACKED_CLIENTS:
            return
        stale = [
            key
            for key, bucket in self._hits.items()
            if not bucket or bucket[-1] <= cutoff
        ]
        for key in stale:
            del self._hits[key]


_LIMITER = SlidingWindowLimiter()
_STATE_LOCK = threading.Lock()
_RESERVATIONS = 0
_COUNTERS = {"admitted": 0, "rate_limited": 0, "concurrency_limited": 0}


def _as_ip(raw: str) -> Optional[IPAddress]:
    value = (raw or "").strip()
    if not value:
        return None
    # Tolerate "host:port" and "[v6]:port" forms from proxy headers.
    if value.startswith("[") and "]" in value:
        value = value[1 : value.index("]")]
    elif value.count(":") == 1 and "." in value:
        value = value.rsplit(":", 1)[0]
    try:
        return ipaddress.ip_address(value)
    except ValueError:
        return None


def _trusted_networks(entries: Sequence[str]) -> list[IPNetwork]:
    networks: list[IPNetwork] = []
    for entry in entries:
        try:
            networks.append(ipaddress.ip_network(entry, strict=False))
        except ValueError:
            # An invalid entry cannot grant trust — fail closed.
            continue
    return networks


def client_identity(request: Request, trusted_proxies: Sequence[str]) -> str:
    """Return the rate-limit key for a request.

    ``X-Forwarded-For`` is only consulted when the immediate socket peer is a
    configured trusted proxy. The header is walked right-to-left so a client
    cannot prepend a fake address ahead of the hop its proxy appended.
    """
    peer_raw = request.client.host if request.client else ""
    peer = _as_ip(peer_raw)
    peer_key = str(peer) if peer is not None else (peer_raw or "unknown")
    networks = _trusted_networks(trusted_proxies)
    if peer is None or not any(peer in network for network in networks):
        return peer_key

    forwarded = request.headers.get("x-forwarded-for", "")
    hops = [hop.strip() for hop in forwarded.split(",") if hop.strip()]
    for raw in reversed(hops):
        address = _as_ip(raw)
        if address is None:
            # Never guess at an unparseable hop; the trusted peer is the
            # best identity we actually observed.
            return peer_key
        if not any(address in network for network in networks):
            return str(address)
    return peer_key


@contextmanager
def admission(
    settings: Settings, store, *, client_key: str
) -> Iterator[None]:
    """Admit one run submission or raise :class:`FairUseError`.

    The caller must keep the context active at least until the new run record
    is saved; the in-process reservation covers that gap.
    """
    global _RESERVATIONS

    wait = _LIMITER.hit(
        client_key,
        limit=settings.rate_limit_requests,
        window_seconds=settings.rate_limit_window_seconds,
    )
    if wait > 0:
        with _STATE_LOCK:
            _COUNTERS["rate_limited"] += 1
        raise FairUseError(
            (
                f"rate limit exceeded: at most {settings.rate_limit_requests} "
                f"run submission(s) per {settings.rate_limit_window_seconds:g}s"
            ),
            retry_after=wait,
        )

    with _STATE_LOCK:
        active = store.count_active_runs() + _RESERVATIONS
        if active >= settings.max_concurrent_runs:
            _COUNTERS["concurrency_limited"] += 1
            raise FairUseError(
                (
                    f"concurrent-run limit reached: {active} of "
                    f"{settings.max_concurrent_runs} active; retry when a "
                    "running job finishes"
                ),
                retry_after=30,
            )
        _RESERVATIONS += 1
        _COUNTERS["admitted"] += 1

    try:
        yield
    finally:
        with _STATE_LOCK:
            _RESERVATIONS = max(0, _RESERVATIONS - 1)


def metrics_snapshot(settings: Settings, store) -> dict:
    """Admission-control state for ``GET /api/metrics``."""
    with _STATE_LOCK:
        counters = dict(_COUNTERS)
        reservations = _RESERVATIONS
    return {
        "active_runs": store.count_active_runs(),
        "reservations": reservations,
        "max_concurrent_runs": settings.max_concurrent_runs,
        "rate_limit_requests": settings.rate_limit_requests,
        "rate_limit_window_seconds": settings.rate_limit_window_seconds,
        "clients_in_window": _LIMITER.active_clients(),
        "admitted": counters["admitted"],
        "rate_limited": counters["rate_limited"],
        "concurrency_limited": counters["concurrency_limited"],
    }


def reset_state() -> None:
    """Clear limiter and counters (tests, or an explicit admin reset)."""
    global _RESERVATIONS
    _LIMITER.reset()
    with _STATE_LOCK:
        _RESERVATIONS = 0
        for key in _COUNTERS:
            _COUNTERS[key] = 0
