"""OpenAI-compatible chat-completions adapter for Ollama Cloud.

Boundaries enforced for every call: hard request timeout, at most 2
retries (429/5xx only) with capped backoff, https-only endpoint with
redirects refused. The base URL is operator-configured, never user input.
"""

from __future__ import annotations

import os
import time
from typing import Optional

import httpx

from repomate_core.models.base import ModelError, ModelProvider, ModelResult

DEFAULT_BASE_URL = "https://ollama.com/v1"
DEFAULT_MODEL = "gemma4:31b"
DEFAULT_OLLAMA_MODELS = "gemma4:31b,gpt-oss:120b"
_MAX_RETRIES = 2


def _env(*names: str, default: str = "") -> str:
    for name in names:
        value = os.environ.get(name, "").strip()
        if value:
            return value
    return default


def model_timeout_from_env(default: float = 240.0) -> float:
    """Wall-time budget per gateway call. Evidence-heavy planner prompts on
    reasoning models can legitimately exceed a minute, so the default is
    generous and tunable via ``OLLAMA_TIMEOUT_SECONDS``."""
    raw = _env("OLLAMA_TIMEOUT_SECONDS")
    try:
        return float(raw) if raw else default
    except ValueError:
        return default


def model_retries_from_env(default: int = _MAX_RETRIES) -> int:
    """Retry budget for retryable gateway failures (429/5xx/524).

    Cloudflare's 524 (origin timeout) is common on slow reasoning models:
    the gateway is still working but the edge gave up. The default of 2
    retries proved too thin in practice, so it is tunable via
    ``OLLAMA_MAX_RETRIES`` and capped to keep a run bounded.
    """
    raw = _env("OLLAMA_MAX_RETRIES")
    if not raw:
        return default
    try:
        return max(0, min(int(raw), 6))
    except ValueError:
        return default


class OpenAIProvider:
    """Chat-completions client verified against Ollama Cloud."""

    def __init__(
        self,
        api_key: str,
        *,
        base_url: Optional[str] = None,
        model: Optional[str] = None,
        client: Optional[httpx.Client] = None,
        max_retries: Optional[int] = None,
    ) -> None:
        if not api_key:
            raise ModelError("OpenAIProvider requires an API key")
        self._api_key = api_key
        self.base_url = (
            base_url or _env("OLLAMA_BASE_URL", default=DEFAULT_BASE_URL)
        ).rstrip("/")
        self.model_id = model or _env("OLLAMA_MODEL", default=DEFAULT_MODEL)
        if not self.base_url.startswith("https://"):
            raise ModelError("OLLAMA_BASE_URL must be https")
        self._injected_client = client
        self._max_retries = (
            max_retries if max_retries is not None else model_retries_from_env()
        )

    @property
    def name(self) -> str:
        return "openai"

    def complete(
        self,
        *,
        system: str,
        user: str,
        max_output_tokens: int = 2048,
        timeout: float = 60.0,
        json_mode: bool = False,
    ) -> ModelResult:
        payload = {
            "model": self.model_id,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "temperature": 0.2,
            "max_tokens": max_output_tokens,
        }
        if json_mode:
            # Ask the gateway to enforce a JSON object; models writing
            # markdown bodies otherwise break their own JSON strings.
            payload["response_format"] = {"type": "json_object"}
        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
        }

        last_error = ""
        owns_client = self._injected_client is None
        client = self._injected_client or httpx.Client(
            timeout=timeout, follow_redirects=False
        )
        try:
            for attempt in range(self._max_retries + 1):
                result = _post_once(client, self.base_url, payload, headers)
                if isinstance(result, ModelResult):
                    return result
                if result.retryable and attempt < self._max_retries:
                    last_error = result.error
                    # Capped exponential backoff: 524s mean the origin is
                    # still working, so a longer pause beats a fast retry.
                    time.sleep(min(2.0 * (attempt + 1), 8.0))
                    continue
                if result.drop_response_format and "response_format" in payload:
                    # Gateway rejects JSON mode — fall back to prompting only.
                    payload.pop("response_format")
                    continue
                raise ModelError(result.error)
            raise ModelError(f"model gateway error after retries: {last_error}")
        finally:
            if owns_client:
                client.close()


class FallbackProvider:
    def __init__(self, providers: list[ModelProvider]) -> None:
        self._providers = providers
        self._active_index = 0

    @property
    def name(self) -> str:
        return self._providers[self._active_index].name

    @property
    def model_id(self) -> str:
        return self._providers[self._active_index].model_id

    def complete(
        self,
        *,
        system: str,
        user: str,
        max_output_tokens: int = 2048,
        timeout: float = 60.0,
        json_mode: bool = False,
    ) -> ModelResult:
        errors = []
        for index in range(self._active_index, len(self._providers)):
            provider = self._providers[index]
            try:
                result = provider.complete(
                    system=system,
                    user=user,
                    max_output_tokens=max_output_tokens,
                    timeout=timeout,
                    json_mode=json_mode,
                )
            except ModelError as exc:
                errors.append(f"{provider.name}/{provider.model_id}: {exc}")
                continue
            self._active_index = index
            return result
        raise ModelError("model fallback chain exhausted: " + " | ".join(errors))


class _Attempt:
    """Internal outcome of one HTTP attempt."""

    def __init__(self, error: str, *, retryable: bool, drop_response_format: bool = False) -> None:
        self.error = error
        self.retryable = retryable
        self.drop_response_format = drop_response_format


def _post_once(client: httpx.Client, base_url: str, payload: dict, headers: dict):
    url = f"{base_url}/chat/completions"
    try:
        response = client.post(url, json=payload, headers=headers)
    except httpx.TimeoutException as exc:
        raise ModelError(f"model request timed out after {client.timeout}") from exc
    except httpx.HTTPError as exc:
        return _Attempt(f"model gateway unreachable: {exc}", retryable=True)

    if response.status_code == 200:
        try:
            body = response.json()
            text = body["choices"][0]["message"]["content"]
        except (ValueError, KeyError, IndexError, TypeError) as exc:
            raise ModelError(
                f"model gateway returned an unexpected payload: {exc}"
            ) from exc
        return ModelResult(
            text=text or "",
            provider="openai",
            model=payload["model"],
            usage=body.get("usage"),
        )
    # 524 is Cloudflare's "origin timeout" — the gateway is still working
    # but the edge gave up; a retry often lands on a faster response.
    retryable = response.status_code in (429, 500, 502, 503, 504, 524)
    body_snippet = response.text[:300]
    drop_json_mode = (
        response.status_code == 400 and "response_format" in body_snippet
    )
    return _Attempt(
        f"model gateway error (status {response.status_code}): {body_snippet}",
        retryable=retryable,
        drop_response_format=drop_json_mode,
    )


def provider_from_env() -> Optional[ModelProvider]:
    """Return the configured Ollama model chain, else ``None`` for heuristics."""
    api_key = _env("OLLAMA_API_KEY")
    if not api_key:
        return None
    base_url = _env("OLLAMA_BASE_URL", default=DEFAULT_BASE_URL)
    models = _env("OLLAMA_MODELS", default=DEFAULT_OLLAMA_MODELS)
    try:
        providers: list[ModelProvider] = [
            OpenAIProvider(api_key, base_url=base_url, model=model.strip())
            for model in models.split(",")
            if model.strip()
        ]
    except ModelError:
        return None
    if not providers:
        return None
    if len(providers) == 1:
        return providers[0]
    return FallbackProvider(providers)
