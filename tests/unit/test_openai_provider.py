"""OpenAI-compatible gateway provider contract tests (no network).

Covers the behaviours the pipeline depends on: happy path, retry on 429,
no retry on auth failures, hard timeout, malformed payloads, and the
OPENAI_* → VYCE_* environment fallback chain.
"""

import httpx
import pytest

from repomate_core.models import ModelError, ModelResult, OpenAIProvider

KEY = "sk-test"
OK_BODY = {
    "choices": [{"message": {"content": '{"task_type": "DOCUMENTATION"}'}}],
    "usage": {"prompt_tokens": 10, "completion_tokens": 5},
}


def _provider(handler, **kwargs) -> OpenAIProvider:
    client = httpx.Client(transport=httpx.MockTransport(handler))
    return OpenAIProvider(KEY, base_url="https://gateway.test/v1", client=client, **kwargs)


def test_provider_name_is_openai():
    provider = _provider(lambda request: httpx.Response(200, json=OK_BODY))
    assert provider.name == "openai"


def test_success_parses_choices_and_usage():
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        assert request.headers["Authorization"] == f"Bearer {KEY}"
        return httpx.Response(200, json=OK_BODY)

    provider = _provider(handler)
    result = provider.complete(system="s", user="u")
    assert isinstance(result, ModelResult)
    assert result.provider == "openai"
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
        OpenAIProvider(KEY, base_url="http://gateway.test/v1")


class TestEnvFallback:
    def test_openai_env_wins(self, monkeypatch):
        monkeypatch.setenv("OPENAI_API_KEY", "k1")
        monkeypatch.setenv("VYCE_API_KEY", "k2")
        from repomate_core.models.openai import provider_from_env

        provider = provider_from_env()
        assert provider is not None and provider._api_key == "k1"

    def test_legacy_vyce_env_still_works(self, monkeypatch):
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        monkeypatch.setenv("VYCE_API_KEY", "k2")
        monkeypatch.setenv("VYCE_BASE_URL", "https://legacy.test/v1")
        from repomate_core.models.openai import provider_from_env

        provider = provider_from_env()
        assert provider is not None
        assert provider._api_key == "k2"
        assert provider.base_url == "https://legacy.test/v1"

    def test_no_key_returns_none(self, monkeypatch):
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        monkeypatch.delenv("VYCE_API_KEY", raising=False)
        from repomate_core.models.openai import provider_from_env

        assert provider_from_env() is None

    def test_vyce_alias_is_openai_provider(self):
        from repomate_core.models import VyceProvider

        assert VyceProvider is OpenAIProvider
