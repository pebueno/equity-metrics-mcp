"""The tool loop and its guardrails.

The gateway owns everything provider-shaped: which model answers, how long it
may take, how often it may retry, how many tool rounds it gets, and what the
frontend and the audit trail are told afterwards. It reaches data only through
the MCP tools.
"""

import asyncio
import datetime as dt
import json
import logging
import time
import uuid
from dataclasses import dataclass
from typing import Any

from equity_metrics.ai_gateway.contracts import (
    AgentResponse,
    AssistantTurn,
    ChatContext,
    LlmProvider,
    ProviderCompletion,
    ToolCallRequest,
    ToolCallResult,
    ToolPayload,
    ToolResultTurn,
    ToolSpec,
    ToolTrace,
    Turn,
    Usage,
    UserTurn,
)
from equity_metrics.ai_gateway.errors import (
    GatewayTimeoutError,
    ToolIterationLimitError,
    TransientProviderError,
)
from equity_metrics.ai_gateway.prompts import PROMPT_VERSION, SYSTEM_PROMPT
from equity_metrics.ai_gateway.tool_client import McpToolClient
from equity_metrics.mcp_server.audit import correlation_scope, sanitize_arguments

logger = logging.getLogger("equity_metrics.ai_gateway")


@dataclass(frozen=True, slots=True)
class GatewayLimits:
    """The fixed budget one answer may consume."""

    max_tool_iterations: int = 6
    call_timeout_seconds: float = 30.0
    total_timeout_seconds: float = 90.0
    max_retries: int = 2
    retry_backoff_seconds: float = 0.5


class AiGateway:
    """Answers investor questions by driving a provider over the MCP tools."""

    def __init__(
        self,
        provider: LlmProvider,
        tool_client: McpToolClient,
        limits: GatewayLimits | None = None,
    ) -> None:
        self._provider = provider
        self._tools = tool_client
        self._limits = limits or GatewayLimits()

    async def answer(self, question: str, context: ChatContext | None = None) -> AgentResponse:
        """Answer one question, or raise a gateway error describing why not."""
        request_id = (context.request_id if context else None) or uuid.uuid4().hex
        started = time.perf_counter()

        # Tool calls made for this question share the request ID, so an audit row
        # can be traced back to the answer the investor saw.
        with correlation_scope(request_id):
            try:
                async with asyncio.timeout(self._limits.total_timeout_seconds):
                    answer, trace, data, usage, iterations = await self._run_loop(question)
            except TimeoutError as exc:
                raise GatewayTimeoutError(
                    f"Answering exceeded the {self._limits.total_timeout_seconds:g}s budget."
                ) from exc

        return AgentResponse(
            answer=answer,
            request_id=request_id,
            provider=self._provider.name,
            model=self._provider.model,
            prompt_version=PROMPT_VERSION,
            trace=trace,
            data=data,
            usage=usage,
            iterations=iterations,
            duration_ms=max(0, round((time.perf_counter() - started) * 1000)),
            created_at=dt.datetime.now(dt.UTC),
        )

    async def _run_loop(
        self, question: str
    ) -> tuple[str, tuple[ToolTrace, ...], tuple[ToolPayload, ...], Usage, int]:
        """Alternate provider turns and tool calls until an answer or a limit."""
        specs = await self._tools.list_specs()
        turns: tuple[Turn, ...] = (UserTurn(text=question),)
        trace: list[ToolTrace] = []
        data: list[ToolPayload] = []
        usage = Usage()

        for iteration in range(1, self._limits.max_tool_iterations + 1):
            completion = await self._complete(turns, specs)
            usage = usage.plus(completion.usage)

            if completion.text is not None:
                return completion.text, tuple(trace), tuple(data), usage, iteration

            if not completion.tool_calls:
                logger.warning("provider returned neither text nor tool calls; ending the loop")
                return "", tuple(trace), tuple(data), usage, iteration

            turns += (AssistantTurn(tool_calls=completion.tool_calls),)
            results = await self._invoke(completion.tool_calls, trace, data)
            turns += (ToolResultTurn(results=results),)

        raise ToolIterationLimitError(
            f"No answer after {self._limits.max_tool_iterations} tool iterations."
        )

    async def _complete(
        self, turns: tuple[Turn, ...], specs: tuple[ToolSpec, ...]
    ) -> ProviderCompletion:
        """Call the provider, bounding the call and retrying only transient faults."""
        attempt = 0
        while True:
            try:
                async with asyncio.timeout(self._limits.call_timeout_seconds):
                    return await self._provider.complete(SYSTEM_PROMPT, turns, specs)
            except TimeoutError as exc:
                raise GatewayTimeoutError(
                    f"Provider call exceeded the {self._limits.call_timeout_seconds:g}s timeout."
                ) from exc
            except TransientProviderError:
                if attempt >= self._limits.max_retries:
                    raise
                # Only transient provider faults are retried; a rejected request
                # or a domain failure would fail identically on a second attempt.
                delay = self._limits.retry_backoff_seconds * (2**attempt)
                attempt += 1
                logger.warning("transient provider failure; retry %d in %.2fs", attempt, delay)
                if delay:
                    await asyncio.sleep(delay)

    async def _invoke(
        self,
        calls: tuple[ToolCallRequest, ...],
        trace: list[ToolTrace],
        data: list[ToolPayload],
    ) -> tuple[ToolCallResult, ...]:
        """Run the requested tool calls in order, recording each in the trace."""
        results: list[ToolCallResult] = []
        for call in calls:
            outcome = await self._tools.call(call.name, call.arguments)
            trace.append(
                ToolTrace(
                    index=len(trace) + 1,
                    tool=call.name,
                    arguments=_sanitized(call.arguments),
                    status="error" if outcome.is_error else "ok",
                    duration_ms=outcome.duration_ms,
                    error_code=outcome.error_code,
                    truncated=outcome.truncated,
                )
            )
            if not outcome.is_error and not outcome.truncated:
                payload = _parsed(outcome.payload)
                if payload is not None:
                    data.append(ToolPayload(tool=call.name, data=payload))
            results.append(
                ToolCallResult(
                    id=call.id,
                    name=call.name,
                    arguments=call.arguments,
                    payload=outcome.payload,
                    is_error=outcome.is_error,
                    error_code=outcome.error_code,
                )
            )
        return tuple(results)


def _parsed(payload: str) -> dict[str, Any] | None:
    """Decode a tool payload for the UI, ignoring anything not a JSON object."""
    try:
        decoded = json.loads(payload)
    except json.JSONDecodeError:
        return None
    return decoded if isinstance(decoded, dict) else None


def _sanitized(arguments: dict[str, object]) -> dict[str, object]:
    """Reuse the audit sanitizer so the visible trace and the audit row agree."""
    return sanitize_arguments(dict(arguments))
