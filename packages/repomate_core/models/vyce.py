"""Back-compat shim: the Vyce adapter was renamed to :class:`OpenAIProvider`
when the gateway was confirmed to be a standard OpenAI-compatible API.

Import from :mod:`repomate_core.models` (or ``.openai``) instead.
"""

from repomate_core.models.openai import (  # noqa: F401
    DEFAULT_BASE_URL,
    DEFAULT_MODEL,
    OpenAIProvider,
    VyceProvider,
    model_timeout_from_env,
    provider_from_env,
)
