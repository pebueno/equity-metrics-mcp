"""Provider selection.

`mock` is the default and needs no credential, so the application and every
test run offline. A live provider is reachable only through configuration.
"""

from equity_metrics.ai_gateway.contracts import LlmProvider
from equity_metrics.ai_gateway.errors import ProviderConfigurationError
from equity_metrics.ai_gateway.providers.mock import MockProvider
from equity_metrics.config import Settings

__all__ = ["MockProvider", "build_provider"]


def build_provider(settings: Settings) -> LlmProvider:
    """Build the configured provider, or explain why it cannot be built."""
    provider = settings.llm_provider.strip().lower()
    if provider == "mock":
        return MockProvider(model=settings.llm_model)
    if provider == "anthropic":
        from equity_metrics.ai_gateway.providers.anthropic_provider import (
            DEFAULT_MODEL,
            AnthropicProvider,
        )

        model = settings.llm_model if settings.llm_model != "mock-model" else DEFAULT_MODEL
        return AnthropicProvider(model=model, api_key=settings.llm_api_key)
    raise ProviderConfigurationError(
        f"Unknown LLM_PROVIDER {settings.llm_provider!r}. Supported values: mock, anthropic."
    )
