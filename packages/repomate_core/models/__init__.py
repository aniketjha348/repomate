"""Provider-independent AI model access (OpenAI-compatible protocol)."""

from repomate_core.models.base import (
    ModelBudget,
    ModelBudgetExceeded,
    ModelError,
    ModelProvider,
    ModelResult,
    ModelTimeoutError,
    parse_model_json,
)
from repomate_core.models.openai import (
    DEFAULT_BASE_URL,
    DEFAULT_MODEL,
    FallbackProvider,
    OpenAIProvider,
    model_timeout_from_env,
    provider_from_env,
)

__all__ = [
    "DEFAULT_BASE_URL",
    "DEFAULT_MODEL",
    "FallbackProvider",
    "ModelBudget",
    "ModelBudgetExceeded",
    "ModelError",
    "ModelProvider",
    "ModelResult",
    "ModelTimeoutError",
    "OpenAIProvider",
    "model_timeout_from_env",
    "parse_model_json",
    "provider_from_env",
]
