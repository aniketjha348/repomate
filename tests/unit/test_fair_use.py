"""API fair-use admission: per-client windows, trusted proxies, concurrency."""

import pytest
from starlette.requests import Request

from services.api import fair_use
from services.api.config import Settings


class _Store:
    def __init__(self, active: int = 0) -> None:
        self.active = active

    def count_active_runs(self) -> int:
        return self.active


def _request(peer: str, forwarded: str | None = None) -> Request:
    headers = []
    if forwarded is not None:
        headers.append((b"x-forwarded-for", forwarded.encode("ascii")))
    return Request(
        {
            "type": "http",
            "method": "POST",
            "path": "/api/runs",
            "query_string": b"",
            "headers": headers,
            "client": (peer, 4321),
        }
    )


def _settings(**overrides) -> Settings:
    base = dict(
        rate_limit_requests=10,
        rate_limit_window_seconds=60.0,
        max_concurrent_runs=3,
        trusted_proxies=[],
    )
    base.update(overrides)
    return Settings(**base)


class TestClientIdentity:
    def test_peer_is_used_when_no_proxy_is_trusted(self):
        request = _request("203.0.113.7", forwarded="198.51.100.9")
        assert fair_use.client_identity(request, []) == "203.0.113.7"

    def test_forwarded_header_ignored_from_untrusted_peer(self):
        request = _request("203.0.113.7", forwarded="1.2.3.4")
        assert fair_use.client_identity(request, ["10.0.0.0/8"]) == "203.0.113.7"

    def test_trusted_proxy_uses_rightmost_untrusted_hop(self):
        request = _request(
            "10.0.0.5",
            forwarded="1.2.3.4, 203.0.113.9, 10.0.0.6",
        )
        assert (
            fair_use.client_identity(request, ["10.0.0.0/8"]) == "203.0.113.9"
        )

    def test_unparseable_forwarded_hop_falls_back_to_peer(self):
        request = _request("10.0.0.5", forwarded="not-an-ip")
        assert fair_use.client_identity(request, ["10.0.0.0/8"]) == "10.0.0.5"

    def test_ipv6_is_normalized(self):
        request = _request("2001:db8::1")
        assert fair_use.client_identity(request, []) == "2001:db8::1"


class TestSlidingWindowLimiter:
    def test_allows_limit_then_reports_retry(self):
        limiter = fair_use.SlidingWindowLimiter()
        assert limiter.hit("a", limit=2, window_seconds=60) == 0.0
        assert limiter.hit("a", limit=2, window_seconds=60) == 0.0
        assert limiter.hit("a", limit=2, window_seconds=60) > 0
        # A different client has its own window.
        assert limiter.hit("b", limit=2, window_seconds=60) == 0.0

    def test_rejected_request_does_not_extend_the_window(self):
        limiter = fair_use.SlidingWindowLimiter()
        limiter.hit("a", limit=1, window_seconds=60)
        first = limiter.hit("a", limit=1, window_seconds=60)
        second = limiter.hit("a", limit=1, window_seconds=60)
        assert first > 0 and second > 0
        assert second <= first + 1


class TestAdmission:
    def test_rate_limit_rejects_with_retry_after(self):
        settings = _settings(rate_limit_requests=2)
        store = _Store()
        with fair_use.admission(settings, store, client_key="a"):
            pass
        with fair_use.admission(settings, store, client_key="a"):
            pass

        with pytest.raises(fair_use.FairUseError) as excinfo:
            with fair_use.admission(settings, store, client_key="a"):
                pass
        assert excinfo.value.retry_after >= 1
        assert "rate limit" in str(excinfo.value)

        snapshot = fair_use.metrics_snapshot(settings, store)
        assert snapshot["rate_limited"] == 1
        assert snapshot["admitted"] == 2

    def test_concurrent_cap_uses_store_and_reservations(self):
        settings = _settings(max_concurrent_runs=1)
        store = _Store(active=0)

        with pytest.raises(fair_use.FairUseError, match="concurrent-run"):
            with fair_use.admission(settings, store, client_key="a"):
                with fair_use.admission(settings, store, client_key="b"):
                    pass
        # The outer reservation was released again.
        assert fair_use.metrics_snapshot(settings, store)["reservations"] == 0

        store.active = 1
        with pytest.raises(fair_use.FairUseError, match="concurrent-run"):
            with fair_use.admission(settings, store, client_key="a"):
                pass
        assert fair_use.metrics_snapshot(settings, store)["concurrency_limited"] == 2

    def test_reservation_covers_the_save_gap(self):
        settings = _settings(max_concurrent_runs=2)
        store = _Store(active=1)
        with fair_use.admission(settings, store, client_key="a"):
            snapshot = fair_use.metrics_snapshot(settings, store)
            assert snapshot["active_runs"] == 1
            assert snapshot["reservations"] == 1
        assert fair_use.metrics_snapshot(settings, store)["reservations"] == 0
