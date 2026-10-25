"""Vyce provider contract tests against a mocked gateway (no network).

Covers the behaviours the pipeline depends on: happy path, retry on 429,
no retry on auth failures, hard timeout, and malformed payloads.
"""

import httpx
import pytest

from repomate_core.models import ModelError, ModelResult, VyceProvider

KEY = "sk-test"
OK_BODY = {
    "choices": [{"message": {"content": '{"task_type": "DOCUMENTATION"}'}}],
    "usage": {"prompt_tokens": 10, "completion_tokens": 5},
}


def _provider(handler) -> VyceProvider:
    client = httpx.Client(transport=httpx.MockTransport(handler))
    return VyceProvider(KEY, base_url="https://vyceai.test/v1", client=client)


def test_success_parses_choices_and_usage():
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        assert request.headers["Authorization"] == f"Bearer {KEY}"
        return httpx.Response(200, json=OK_BODY)

    provider = _provider(handler)
    result = provider.complete(system="s", user="u")
    assert isinstance(result, ModelResult)
    assert "DOCUMENTATION" in result.text
    assert result.usage == {"prompt_tokens": 10, "completion_tokens": 5}
    assert len(calls) == 1


def test_retries_once_on_429_then_succeeds():
    attempts = []

    def handler(request: httpx.Request) -> httpx.Response:
        attempts.append(1)
        if len(attempts) == 1:
            return httpx.Response(429, json={"error": "rate limited"})
        return httpx.Response(200, json=OK_BODY)

    provider = _provider(handler)
    result = provider.complete(system="s", user="u")
    assert "DOCUMENTATION" in result.text
    assert len(attempts) == 2


def test_gives_up_after_capped_retries():
    attempts = []

    def handler(request: httpx.Request) -> httpx.Response:
        attempts.append(1)
        return httpx.Response(503, json={"error": "down"})

    provider = _provider(handler)
    with pytest.raises(ModelError, match="503"):
        provider.complete(system="s", user="u")
    assert len(attempts) == 3  # initial + 2 retries, never more


def test_auth_error_is_not_retried():
    attempts = []

    def handler(request: httpx.Request) -> httpx.Response:
        attempts.append(1)
        return httpx.Response(401, json={"error": "bad key"})

    provider = _provider(handler)
    with pytest.raises(ModelError, match="401"):
        provider.complete(system="s", user="u")
    assert len(attempts) == 1


def test_transport_timeout_raises_model_error():
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("timed out")

    provider = _provider(handler)
    with pytest.raises(ModelError):
        provider.complete(system="s", user="u", timeout=0.1)


def test_malformed_payload_raises_model_error():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"unexpected": True})

    provider = _provider(handler)
    with pytest.raises(ModelError, match="unexpected payload"):
        provider.complete(system="s", user="u")


def test_non_https_base_url_rejected():
    with pytest.raises(ModelError, match="https"):
        VyceProvider(KEY, base_url="http://vyceai.test/v1")
