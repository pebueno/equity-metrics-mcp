"""Provider-independent types for the AI gateway.

Nothing here mentions a vendor. A provider adapter translates these types to and
from its own wire format, which is what keeps the gateway swappable and lets a
future standalone deployment keep the same contract.
"""

import datetime as dt
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any, Literal, Protocol, runtime_checkable

ToolStatus = Literal["ok", "error"]


@dataclass(frozen=True, slots=True)
class ToolSpec:
    """A tool the provider may call, described in JSON Schema."""

    name: str
    description: str
    input_schema: dict[str, Any]


@dataclass(frozen=True, slots=True)
class ToolCallRequest:
    """A provider's request to invoke one tool."""

    id: str
    name: str
    arguments: dict[str, Any]


@dataclass(frozen=True, slots=True)
class ToolCallResult:
    """The outcome of one tool invocation, as the provider will see it."""

    id: str
    name: str
    arguments: dict[str, Any]
    payload: str
    is_error: bool
    error_code: str | None = None


@dataclass(frozen=True, slots=True)
class UserTurn:
    """The investor's question."""

    text: str


@dataclass(frozen=True, slots=True)
class AssistantTurn:
    """A provider response: either final text or a batch of tool calls."""

    text: str | None = None
    tool_calls: tuple[ToolCallRequest, ...] = ()


@dataclass(frozen=True, slots=True)
class ToolResultTurn:
    """Results handed back to the provider after it requested tool calls."""

    results: tuple[ToolCallResult, ...]


Turn = UserTurn | AssistantTurn | ToolResultTurn


@dataclass(frozen=True, slots=True)
class Usage:
    """Token counts and estimated cost for one answer."""

    input_tokens: int = 0
    output_tokens: int = 0
    estimated_cost_usd: Decimal | None = None

    def plus(self, other: "Usage") -> "Usage":
        """Accumulate usage across the iterations of one tool loop."""
        cost: Decimal | None
        if self.estimated_cost_usd is None and other.estimated_cost_usd is None:
            cost = None
        else:
            cost = (self.estimated_cost_usd or Decimal(0)) + (
                other.estimated_cost_usd or Decimal(0)
            )
        return Usage(
            input_tokens=self.input_tokens + other.input_tokens,
            output_tokens=self.output_tokens + other.output_tokens,
            estimated_cost_usd=cost,
        )


@dataclass(frozen=True, slots=True)
class ProviderCompletion:
    """One provider turn: final text, or tool calls to run, never both empty."""

    text: str | None = None
    tool_calls: tuple[ToolCallRequest, ...] = ()
    usage: Usage = field(default_factory=Usage)


@runtime_checkable
class LlmProvider(Protocol):
    """The narrow interface every provider adapter implements."""

    @property
    def name(self) -> str:
        """Provider identifier recorded in the trace, e.g. `mock`."""

    @property
    def model(self) -> str:
        """Model identifier recorded in the trace."""

    async def complete(
        self, system: str, turns: tuple[Turn, ...], tools: tuple[ToolSpec, ...]
    ) -> ProviderCompletion:
        """Produce the next assistant turn for the given conversation."""


@dataclass(frozen=True, slots=True)
class ToolTrace:
    """One entry in the ordered, user-visible record of what the agent did."""

    index: int
    tool: str
    arguments: dict[str, Any]
    status: ToolStatus
    duration_ms: int
    error_code: str | None = None
    truncated: bool = False


@dataclass(frozen=True, slots=True)
class ChatContext:
    """Caller-supplied context for one question."""

    request_id: str | None = None


@dataclass(frozen=True, slots=True)
class AgentResponse:
    """The gateway's answer plus everything needed to audit how it was produced."""

    answer: str
    request_id: str
    provider: str
    model: str
    prompt_version: str
    trace: tuple[ToolTrace, ...]
    usage: Usage
    iterations: int
    duration_ms: int
    created_at: dt.datetime
