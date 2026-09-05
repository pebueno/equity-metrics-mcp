"""The gateway's only route to data: the MCP tools.

The gateway never touches PostgreSQL. It discovers and invokes tools through
this adapter, which is also where a tool result is bounded before it is fed
back to a provider.
"""

import json
import time
from dataclasses import dataclass
from typing import Any

from mcp.server.mcpserver import MCPServer
from mcp.types import CallToolResult

from equity_metrics.ai_gateway.contracts import ToolSpec

# A single tool result must not be able to blow up the provider request.
MAX_TOOL_RESULT_CHARS = 20_000
TRUNCATION_NOTICE = '{"truncated": true, "reason": "tool result exceeded the response-size bound"}'


@dataclass(frozen=True, slots=True)
class ToolOutcome:
    """What one tool invocation produced, with its cost in wall-clock time."""

    payload: str
    is_error: bool
    error_code: str | None
    duration_ms: int
    truncated: bool


class McpToolClient:
    """Invokes MCP tools in process, bounding what comes back."""

    def __init__(self, server: MCPServer[Any], max_result_chars: int = MAX_TOOL_RESULT_CHARS):
        self._server = server
        self._max_result_chars = max_result_chars

    async def list_specs(self) -> tuple[ToolSpec, ...]:
        """Describe the available tools for the provider."""
        tools = await self._server.list_tools()
        return tuple(
            ToolSpec(
                name=tool.name,
                description=tool.description or "",
                input_schema=tool.input_schema,
            )
            for tool in tools
        )

    async def call(self, name: str, arguments: dict[str, Any]) -> ToolOutcome:
        """Invoke one tool and return its bounded payload and status."""
        started = time.perf_counter()
        result = await self._server.call_tool(name, arguments)
        duration_ms = max(0, round((time.perf_counter() - started) * 1000))

        if not isinstance(result, CallToolResult):
            # These tools never ask the client for more input; treat anything else
            # as a failed call rather than silently returning an empty answer.
            return ToolOutcome(
                payload='{"isError": true, "error": {"code": "unexpected_tool_response"}}',
                is_error=True,
                error_code="unexpected_tool_response",
                duration_ms=duration_ms,
                truncated=False,
            )

        structured = result.structured_content
        payload = json.dumps(structured) if structured is not None else _text_of(result)

        truncated = len(payload) > self._max_result_chars
        if truncated:
            payload = payload[: self._max_result_chars] + TRUNCATION_NOTICE

        return ToolOutcome(
            payload=payload,
            is_error=bool(result.is_error),
            error_code=_error_code(structured),
            duration_ms=duration_ms,
            truncated=truncated,
        )


def _text_of(result: Any) -> str:
    """Fall back to the text blocks when a tool returns no structured content."""
    blocks = getattr(result, "content", None) or []
    return "".join(block.text for block in blocks if getattr(block, "type", None) == "text")


def _error_code(structured: Any) -> str | None:
    """Read the machine-readable code out of a structured tool error."""
    if isinstance(structured, dict):
        error = structured.get("error")
        if isinstance(error, dict):
            code = error.get("code")
            if isinstance(code, str):
                return code
    return None
