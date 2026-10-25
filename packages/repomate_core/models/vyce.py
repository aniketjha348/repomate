"""Vyce AI gateway adapter (OpenAI-compatible /chat/completions).

Boundaries enforced for every call: hard request timeout, at most 2
retries (429/5xx only) with capped backoff, https-only endpoint with
redirects refused. The base URL is operator-configured via environment
(``VYCE_BASE_URL``), never user input.
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


def model_timeout_from_env(default: float = 240.0) -> float:
    """Wall-time budget per gateway call. Evidence-heavy planner prompts on
    reasoning models can legitimately exceed a minute, so the default is
    generous and tunable via ``VYCE_TIMEOUT_SECONDS``."""
    raw = os.environ.get("VYCE_TIMEOUT_SECONDS", "").strip()
    try:
        return float(raw) if raw else default
    except ValueError:
        return default


class VyceProvider:
    """OpenAI-compatible adapter for the Vyce AI gateway.

    Endpoint verified live against ``https://vyceai.com/v1`` (models list
    + chat completions); configuration stays environment-driven
    (``VYCE_BASE_URL`` / ``VYCE_MODEL``) so switching models is a config
    change, not a code change.
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
            raise ModelError("VyceProvider requires an API key")
        self._api_key = api_key
        self.base_url = (base_url or os.environ.get("VYCE_BASE_URL") or DEFAULT_BASE_URL).rstrip("/")
        self.model_id = model or os.environ.get("VYCE_MODEL") or DEFAULT_MODEL
        if not self.base_url.startswith("https://"):
            raise ModelError("VYCE_BASE_URL must be https")
        self._injected_client = client

    @property
    def name(self) -> str:
        return "vyce"

    def complete(
        self,
        *,
        system: str,
        user: str,
        max_output_tokens: int = 2048,
        timeout: float = 60.0,
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
                raise ModelError(result.error)
            raise ModelError(f"model gateway error after retries: {last_error}")
        finally:
            if owns_client:
                client.close()


class _Attempt:
    """Internal outcome of one HTTP attempt."""

    def __init__(self, error: str, *, retryable: bool) -> None:
        self.error = error
        self.retryable = retryable


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
            provider="vyce",
            model=payload["model"],
            usage=body.get("usage"),
        )
    retryable = response.status_code in (429, 500, 502, 503, 504)
    return _Attempt(
        f"model gateway error (status {response.status_code}): {response.text[:300]}",
        retryable=retryable,
    )


def provider_from_env() -> Optional[VyceProvider]:
    """Return a Vyce provider when configured, else ``None``.

    ``None`` means the pipeline runs with the deterministic heuristic
    planner — every artifact is then explicitly labelled as such.
    """
    api_key = os.environ.get("VYCE_API_KEY", "").strip()
    if not api_key:
        return None
    try:
        return VyceProvider(api_key)
    except ModelError:
        return None
