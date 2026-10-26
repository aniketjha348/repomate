"""Provider-agnostic model access primitives.

The pipeline only ever talks to the :class:`ModelProvider` protocol, so
gateways can be swapped without touching orchestration.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Optional, Protocol

from repomate_core.contracts import ModelBudgetLimits, ModelBudgetReport


class ModelError(RuntimeError):
    """Controlled model failure (transport, auth, unparsable output)."""


class ModelTimeoutError(ModelError):
    pass


class ModelBudgetExceeded(ModelError):
    """The per-run model call or token budget refused another call."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


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


def _usage_tokens(usage: dict[str, Any], *names: str) -> Optional[int]:
    for name in names:
        value = usage.get(name)
        if isinstance(value, (int, float)) and value >= 0:
            return int(value)
    return None


class ModelBudget:
    """Enforces per-run model call and token caps.

    Callers must invoke :meth:`start_call` before each provider request and
    :meth:`record_result` after a successful response. A call that never
    returns still consumed its slot, which is why the call counter advances
    before the request is made.
    """

    def __init__(self, limits: Optional[ModelBudgetLimits] = None) -> None:
        self.limits = limits or ModelBudgetLimits()
        self.calls = 0
        self.prompt_tokens = 0
        self.completion_tokens = 0
        self._reported = 0
        self._estimated = 0
        self._exhausted_reason = ""
        self._pending_estimate = 0

    @property
    def total_tokens(self) -> int:
        return self.prompt_tokens + self.completion_tokens

    def start_call(self, *, estimated_prompt_tokens: int = 0) -> None:
        if self.calls >= self.limits.max_calls:
            self._exhausted_reason = (
                f"model call budget exhausted: {self.calls} of "
                f"{self.limits.max_calls} calls used"
            )
            raise ModelBudgetExceeded(self._exhausted_reason)
        if self.total_tokens + max(0, estimated_prompt_tokens) >= self.limits.max_tokens:
            self._exhausted_reason = (
                f"model token budget exhausted: {self.total_tokens} of "
                f"{self.limits.max_tokens} tokens used"
            )
            raise ModelBudgetExceeded(self._exhausted_reason)
        self.calls += 1
        self._pending_estimate = max(0, estimated_prompt_tokens)

    def record_result(
        self,
        result: ModelResult,
        *,
        estimated_prompt_tokens: Optional[int] = None,
    ) -> None:
        """Record reported usage, falling back to a conservative estimate.

        A gateway that omits ``usage`` must not make the token budget
        unenforceable. Estimated counts are labelled as such in the report.
        The prompt estimate passed to :meth:`start_call` is reused unless the
        caller supplies a corrected one.
        """
        estimate = (
            self._pending_estimate
            if estimated_prompt_tokens is None
            else max(0, estimated_prompt_tokens)
        )
        usage = result.usage or {}
        prompt = _usage_tokens(usage, "prompt_tokens", "input_tokens")
        completion = _usage_tokens(usage, "completion_tokens", "output_tokens")
        if prompt is None or completion is None:
            prompt = prompt if prompt is not None else estimate
            completion = (
                completion
                if completion is not None
                else max(0, len(result.text) // 4)
            )
            self._estimated += 1
        else:
            self._reported += 1
        self.prompt_tokens += prompt
        self.completion_tokens += completion

    def exhausted(self) -> bool:
        return self.calls >= self.limits.max_calls or self.total_tokens >= self.limits.max_tokens

    def report(self) -> ModelBudgetReport:
        if self._reported and self._estimated:
            source = "mixed"
        elif self._reported:
            source = "reported"
        elif self._estimated:
            source = "estimated"
        else:
            source = "none"
        reason = self._exhausted_reason
        if not reason and self.exhausted():
            if self.calls >= self.limits.max_calls:
                reason = (
                    f"model call budget reached: {self.calls} of "
                    f"{self.limits.max_calls} calls used"
                )
            else:
                reason = (
                    f"model token budget reached: {self.total_tokens} of "
                    f"{self.limits.max_tokens} tokens used"
                )
        return ModelBudgetReport(
            limits=self.limits,
            calls=self.calls,
            prompt_tokens=self.prompt_tokens,
            completion_tokens=self.completion_tokens,
            total_tokens=self.total_tokens,
            usage_source=source,  # type: ignore[arg-type]
            exhausted=self.exhausted(),
            reason=reason,
        )
