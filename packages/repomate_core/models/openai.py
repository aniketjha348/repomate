"""OpenAI-compatible chat-completions gateway adapter.

Vyce AI (and any OpenAI-compatible gateway) speaks the standard
``/chat/completions`` dialect, so the adapter is named for the protocol,
not the vendor: :class:`OpenAIProvider`. Configuration is entirely
environment-driven (``OPENAI_BASE_URL`` / ``OPENAI_MODEL`` /
``OPENAI_API_KEY``) — the legacy ``VYCE_*`` names still work and are
read as fallbacks, so existing deployments keep running unchanged.

Boundaries enforced for every call: hard request timeout, at most 2
retries (429/5xx only) with capped backoff, https-only endpoint with
redirects refused. The base URL is operator-configured, never user input.
"""

from __future__ import annotations

import os
import time
from typing import Optional

import httpx

from repomate_core.models.base import ModelError, ModelResult

DEFAULT_BASE_URL = "https://vyceai.com/v1"
DEFAULT_MODEL = "deepseek-v4.1"
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
    generous and tunable via ``OPENAI_TIMEOUT_SECONDS``."""
    raw = _env("OPENAI_TIMEOUT_SECONDS", "VYCE_TIMEOUT_SECONDS")
    try:
        return float(raw) if raw else default
    except ValueError:
        return default


class OpenAIProvider:
    """Verified live against the Vyce AI deployment of the OpenAI
    chat-completions API (models list + completions); swapping gateways is
    a config change, not a code change.
    """

    def __init__(
        self,
        api_key: str,
        *,
        base_url: Optional[str] = None,
        model: Optional[str] = None,
        client: Optional[httpx.Client] = None,
    ) -> None:
        if not api_key:
            raise ModelError("OpenAIProvider requires an API key")
        self._api_key = api_key
        self.base_url = (
            base_url
            or _env("OPENAI_BASE_URL", "VYCE_BASE_URL", default=DEFAULT_BASE_URL)
        ).rstrip("/")
        self.model_id = model or _env("OPENAI_MODEL", "VYCE_MODEL", default=DEFAULT_MODEL)
        if not self.base_url.startswith("https://"):
            raise ModelError("OPENAI_BASE_URL must be https")
        self._injected_client = client

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
            for attempt in range(_MAX_RETRIES + 1):
                result = _post_once(client, self.base_url, payload, headers)
                if isinstance(result, ModelResult):
                    return result
                if result.retryable and attempt < _MAX_RETRIES:
                    last_error = result.error
                    time.sleep(min(2.0 * (attempt + 1), 5.0))
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


# Legacy alias: the adapter shipped as VyceProvider before it was
# generalized to the protocol name.
VyceProvider = OpenAIProvider


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


def provider_from_env() -> Optional[OpenAIProvider]:
    """Return a provider when configured, else ``None``.

    ``None`` means the pipeline runs with the deterministic heuristic
    planner — every artifact is then explicitly labelled as such.
    """
    api_key = _env("OPENAI_API_KEY", "VYCE_API_KEY")
    if not api_key:
        return None
    try:
        return OpenAIProvider(api_key)
    except ModelError:
        return None
