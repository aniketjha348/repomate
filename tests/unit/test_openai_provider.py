"""Ollama-compatible provider and model-chain contract tests (no network).

Covers the behaviours the pipeline depends on: happy path, retry on 429,
no retry on auth failures, hard timeout, malformed payloads, model
fallback, and the ``OLLAMA_*`` environment configuration chain.
"""

import httpx
import pytest

from repomate_core.models import (
    FallbackProvider,
    ModelError,
    ModelResult,
    OpenAIProvider,
)

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


class _StubProvider:
    name = "openai"

    def __init__(self, model_id: str, *outcomes: object) -> None:
        self.model_id = model_id
        self._outcomes = list(outcomes)
        self.calls = 0

    def complete(self, **kwargs) -> ModelResult:
        self.calls += 1
        outcome = self._outcomes.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return ModelResult(text=str(outcome), provider=self.name, model=self.model_id)


def test_fallback_uses_next_model_and_remembers_success():
    primary = _StubProvider("gemma4:31b", ModelError("down"))
    fallback = _StubProvider("gpt-oss:120b", "first", "second")
    provider = FallbackProvider([primary, fallback])

    assert provider.complete(system="s", user="u").text == "first"
    assert provider.model_id == "gpt-oss:120b"
    assert provider.complete(system="s", user="u").text == "second"
    assert primary.calls == 1
    assert fallback.calls == 2


def test_fallback_reports_all_model_failures():
    primary = _StubProvider("gemma4:31b", ModelError("down"))
    fallback = _StubProvider("gpt-oss:120b", ModelError("unavailable"))
    provider = FallbackProvider([primary, fallback])

    with pytest.raises(ModelError) as exc_info:
        provider.complete(system="s", user="u")
    assert "gemma4:31b: down" in str(exc_info.value)
    assert "gpt-oss:120b: unavailable" in str(exc_info.value)


def test_planner_name_tracks_successful_fallback():
    from repomate_core.planning.model_planner import ModelPlanner

    primary = _StubProvider("gemma4:31b", ModelError("down"))
    fallback = _StubProvider("gpt-oss:120b", "ok")
    planner = ModelPlanner(FallbackProvider([primary, fallback]))

    assert planner.name == "model:openai/gemma4:31b"
    planner.provider.complete(system="s", user="u")
    assert planner.name == "model:openai/gpt-oss:120b"


class TestOllamaEnvironment:
    @pytest.fixture(autouse=True)
    def clear_provider_environment(self, monkeypatch):
        for key in (
            "OLLAMA_API_KEY",
            "OLLAMA_BASE_URL",
            "OLLAMA_MODELS",
            "OLLAMA_MODEL",
        ):
            monkeypatch.delenv(key, raising=False)

    def test_no_key_returns_none(self, monkeypatch):
        from repomate_core.models.openai import provider_from_env

        assert provider_from_env() is None

    def test_ollama_models_are_tried_in_order(self, monkeypatch):
        monkeypatch.setenv("OLLAMA_API_KEY", "ollama-key")
        monkeypatch.setenv("OLLAMA_MODELS", "gemma4:31b,gpt-oss:120b")
        from repomate_core.models.openai import provider_from_env

        provider = provider_from_env()
        assert isinstance(provider, FallbackProvider)
        assert [p.model_id for p in provider._providers] == [
            "gemma4:31b",
            "gpt-oss:120b",
        ]
        assert all(p.base_url == "https://ollama.com/v1" for p in provider._providers)

    def test_single_ollama_model_is_not_wrapped(self, monkeypatch):
        monkeypatch.setenv("OLLAMA_API_KEY", "ollama-key")
        monkeypatch.setenv("OLLAMA_MODELS", "gemma4:31b")
        from repomate_core.models.openai import provider_from_env

        provider = provider_from_env()
        assert isinstance(provider, OpenAIProvider)
        assert provider.model_id == "gemma4:31b"
