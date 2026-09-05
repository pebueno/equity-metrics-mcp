"""The chat endpoint.

The route owns no agent logic: it builds the gateway once per process, hands it
the question, and renders the answer with its ordered tool trace.
"""

import datetime as dt
import logging
from functools import lru_cache
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field

from equity_metrics.ai_gateway.contracts import AgentResponse, ChatContext
from equity_metrics.ai_gateway.errors import GatewayError
from equity_metrics.ai_gateway.gateway import AiGateway, GatewayLimits
from equity_metrics.ai_gateway.providers import build_provider
from equity_metrics.ai_gateway.tool_client import McpToolClient
from equity_metrics.config import Settings, get_settings
from equity_metrics.mcp_server.server import create_server

logger = logging.getLogger("equity_metrics.api.chat")

router = APIRouter(prefix="/api")

MAX_QUESTION_LENGTH = 500


class ChatRequest(BaseModel):
    """One investor question."""

    question: str = Field(min_length=1, max_length=MAX_QUESTION_LENGTH)


class ToolTraceItem(BaseModel):
    """One tool call, as shown in the activity panel."""

    index: int
    tool: str
    arguments: dict[str, Any]
    status: str
    duration_ms: int
    error_code: str | None = None
    truncated: bool = False


class ChatResponse(BaseModel):
    """The answer plus everything needed to inspect how it was produced."""

    answer: str
    request_id: str
    provider: str
    model: str
    prompt_version: str
    iterations: int
    duration_ms: int
    created_at: dt.datetime
    trace: list[ToolTraceItem]


@lru_cache
def _gateway() -> AiGateway:
    """Build the gateway once; it holds the MCP server and the provider."""
    settings = get_settings()
    return build_gateway(settings)


def build_gateway(settings: Settings) -> AiGateway:
    """Assemble a gateway from settings, for the app and for tests alike."""
    return AiGateway(
        provider=build_provider(settings),
        tool_client=McpToolClient(create_server()),
        limits=GatewayLimits(
            max_tool_iterations=settings.llm_max_tool_iterations,
            call_timeout_seconds=settings.llm_timeout_seconds,
            total_timeout_seconds=settings.llm_total_timeout_seconds,
            max_retries=settings.llm_max_retries,
        ),
    )


def get_gateway() -> AiGateway:
    """Dependency seam so tests can serve the endpoint from their own gateway."""
    return _gateway()


@router.post("/chat", response_model=ChatResponse)
async def chat(
    request: ChatRequest, gateway: Annotated[AiGateway, Depends(get_gateway)]
) -> ChatResponse:
    """Answer a question through the MCP tools and return the tool trace."""
    try:
        response = await gateway.answer(request.question, ChatContext())
    except GatewayError as exc:
        logger.warning("gateway failed: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"code": exc.code, "message": str(exc)},
        ) from exc
    return _render(response)


def _render(response: AgentResponse) -> ChatResponse:
    return ChatResponse(
        answer=response.answer,
        request_id=response.request_id,
        provider=response.provider,
        model=response.model,
        prompt_version=response.prompt_version,
        iterations=response.iterations,
        duration_ms=response.duration_ms,
        created_at=response.created_at,
        trace=[
            ToolTraceItem(
                index=entry.index,
                tool=entry.tool,
                arguments=entry.arguments,
                status=entry.status,
                duration_ms=entry.duration_ms,
                error_code=entry.error_code,
                truncated=entry.truncated,
            )
            for entry in response.trace
        ],
    )
