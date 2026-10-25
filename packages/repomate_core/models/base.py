"""Provider-agnostic model access primitives.

The pipeline only ever talks to the :class:`ModelProvider` protocol, so
gateways can be swapped without touching orchestration.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Optional, Protocol


class ModelError(RuntimeError):
    """Controlled model failure (transport, auth, unparsable output)."""


class ModelTimeoutError(ModelError):
    pass


@dataclass(frozen=True)
class ModelResult:
    text: str
    provider: str
    model: str
    usage: Optional[dict[str, Any]] = None


class ModelProvider(Protocol):
    name: str
    model_id: str

    def complete(
        self,
        *,
        system: str,
        user: str,
        max_output_tokens: int = 2048,
        timeout: float = 60.0,
    ) -> ModelResult: ...


def parse_model_json(text: str) -> dict[str, Any]:
    """Parse a JSON object out of a model response (code fences tolerated)."""
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.strip("`")
        if cleaned.lower().startswith("json"):
            cleaned = cleaned[4:]
        cleaned = cleaned.strip()
    start, end = cleaned.find("{"), cleaned.rfind("}")
    if start == -1 or end <= start:
        raise ModelError("model response contained no JSON object")
    try:
        data = json.loads(cleaned[start : end + 1])
    except ValueError as exc:
        raise ModelError(f"model response was not valid JSON: {exc}") from exc
    if not isinstance(data, dict):
        raise ModelError("model response was not a JSON object")
    return data
