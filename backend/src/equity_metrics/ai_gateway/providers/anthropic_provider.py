"""Live Anthropic adapter, reachable only when LLM_PROVIDER=anthropic.

The `anthropic` SDK is an optional dependency: it is imported inside the
constructor so the default mock path, and therefore the whole test suite, never
needs the package or a credential. The API key stays inside this module.
"""

import json
from typing import Any

from equity_metrics.ai_gateway.contracts import (
    AssistantTurn,
    ProviderCompletion,
    ToolCallRequest,
    ToolSpec,
    Turn,
    Usage,
    UserTurn,
)
from equity_metrics.ai_gateway.errors import (
    ProviderConfigurationError,
    ProviderFailureError,
    TransientProviderError,
)

DEFAULT_MODEL = "claude-opus-5"
MAX_TOKENS = 16_000


class AnthropicProvider:
    """Translates the gateway's provider-independent turns to the Messages API."""

    def __init__(self, model: str = DEFAULT_MODEL, api_key: str | None = None) -> None:
        try:
            import anthropic
        except ModuleNotFoundError as exc:  # pragma: no cover - optional dependency
            raise ProviderConfigurationError(
                "LLM_PROVIDER=anthropic requires the `anthropic` package: pip install anthropic"
            ) from exc

        if not api_key:
            raise ProviderConfigurationError(
                "LLM_PROVIDER=anthropic requires LLM_API_KEY to be set."
            )

        self._anthropic = anthropic
        # The gateway owns retries and timeouts, so the SDK does not add its own.
        self._client = anthropic.AsyncAnthropic(api_key=api_key, max_retries=0)
        self._model = model

    @property
    def name(self) -> str:
        return "anthropic"

    @property
    def model(self) -> str:
        return self._model

    async def complete(
        self, system: str, turns: tuple[Turn, ...], tools: tuple[ToolSpec, ...]
    ) -> ProviderCompletion:
        """Send one Messages request and translate the response back."""
        try:
            response = await self._client.messages.create(
                model=self._model,
                max_tokens=MAX_TOKENS,
                system=system,
                tools=[
                    {
                        "name": spec.name,
                        "description": spec.description,
                        "input_schema": spec.input_schema,
                    }
                    for spec in tools
                ],
                messages=_to_messages(turns),
            )
        except (
            self._anthropic.RateLimitError,
            self._anthropic.InternalServerError,
            self._anthropic.APIConnectionError,
            self._anthropic.APITimeoutError,
        ) as exc:
            raise TransientProviderError(f"Anthropic call failed transiently: {exc}") from exc
        except self._anthropic.APIStatusError as exc:
            raise ProviderFailureError(f"Anthropic rejected the request: {exc}") from exc

        return _to_completion(response)


def _to_messages(turns: tuple[Turn, ...]) -> list[dict[str, Any]]:
    """Render the conversation in Messages API shape."""
    messages: list[dict[str, Any]] = []
    for turn in turns:
        if isinstance(turn, UserTurn):
            messages.append({"role": "user", "content": turn.text})
        elif isinstance(turn, AssistantTurn):
            content: list[dict[str, Any]] = []
            if turn.text:
                content.append({"type": "text", "text": turn.text})
            content.extend(
                {"type": "tool_use", "id": call.id, "name": call.name, "input": call.arguments}
                for call in turn.tool_calls
            )
            messages.append({"role": "assistant", "content": content})
        else:
            # Every tool result for one assistant turn goes back in a single user
            # message, or the model learns to stop making parallel calls.
            messages.append(
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "tool_result",
                            "tool_use_id": result.id,
                            "content": result.payload,
                            "is_error": result.is_error,
                        }
                        for result in turn.results
                    ],
                }
            )
    return messages


def _to_completion(response: Any) -> ProviderCompletion:
    """Split a response into final text or the tool calls it asked for."""
    text_parts: list[str] = []
    tool_calls: list[ToolCallRequest] = []
    for block in response.content:
        if block.type == "text":
            text_parts.append(block.text)
        elif block.type == "tool_use":
            # Tool inputs are parsed JSON already; never string-match the raw form.
            arguments = block.input if isinstance(block.input, dict) else json.loads(block.input)
            tool_calls.append(ToolCallRequest(id=block.id, name=block.name, arguments=arguments))

    usage = Usage(
        input_tokens=getattr(response.usage, "input_tokens", 0),
        output_tokens=getattr(response.usage, "output_tokens", 0),
    )
    if tool_calls:
        return ProviderCompletion(tool_calls=tuple(tool_calls), usage=usage)
    return ProviderCompletion(text="".join(text_parts), usage=usage)
