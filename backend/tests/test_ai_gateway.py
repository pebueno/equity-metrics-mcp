"""Gateway guardrails and the mock tool loop.

Nothing here touches a network, a credential, or a live provider.
"""

import asyncio
from collections.abc import Callable, Iterator
from typing import Any

import pytest
from mcp.server.mcpserver import MCPServer
from sqlalchemy import Engine, select
from sqlalchemy.orm import Session, sessionmaker

from equity_metrics.ai_gateway.contracts import (
    ChatContext,
    ProviderCompletion,
    ToolCallRequest,
    ToolSpec,
    Turn,
    Usage,
)
from equity_metrics.ai_gateway.errors import (
    GatewayTimeoutError,
    ProviderConfigurationError,
    ProviderFailureError,
    ToolIterationLimitError,
    TransientProviderError,
)
from equity_metrics.ai_gateway.gateway import AiGateway, GatewayLimits
from equity_metrics.ai_gateway.prompts import PROMPT_VERSION
from equity_metrics.ai_gateway.providers import build_provider
from equity_metrics.ai_gateway.providers.mock import MockProvider
from equity_metrics.ai_gateway.tool_client import McpToolClient
from equity_metrics.config import Settings
from equity_metrics.db.models import McpToolCall
from equity_metrics.mcp_server.server import create_server

FAST_LIMITS = GatewayLimits(retry_backoff_seconds=0.0)


@pytest.fixture
def session_factory(seeded_session: Session, engine: Engine) -> Callable[[], Session]:
    return sessionmaker(bind=engine, expire_on_commit=False)


@pytest.fixture
def server(session_factory: Callable[[], Session]) -> Iterator[MCPServer[Any]]:
    with session_factory() as session:
        session.query(McpToolCall).delete()
        session.commit()
    yield create_server(session_factory)


@pytest.fixture
def tool_client(server: MCPServer[Any]) -> McpToolClient:
    return McpToolClient(server)


@pytest.fixture
def gateway(tool_client: McpToolClient) -> AiGateway:
    return AiGateway(MockProvider(), tool_client, FAST_LIMITS)


class ScriptedProvider:
    """A provider that replays a fixed script, for exercising the loop itself."""

    def __init__(self, script: list[ProviderCompletion | Exception]) -> None:
        self.script = script
        self.calls = 0

    @property
    def name(self) -> str:
        return "scripted"

    @property
    def model(self) -> str:
        return "scripted-model"

    async def complete(
        self, system: str, turns: tuple[Turn, ...], tools: tuple[ToolSpec, ...]
    ) -> ProviderCompletion:
        step = self.script[min(self.calls, len(self.script) - 1)]
        self.calls += 1
        if isinstance(step, Exception):
            raise step
        return step


def _search_call() -> ProviderCompletion:
    return ProviderCompletion(
        tool_calls=(
            ToolCallRequest(id="c1", name="search_companies", arguments={"query": "acme"}),
        ),
        usage=Usage(input_tokens=10, output_tokens=2),
    )


class TestMockTooLoop:
    @pytest.mark.anyio
    async def test_answers_a_qtd_question_from_tool_data(self, gateway: AiGateway) -> None:
        response = await gateway.answer("What is ACME's QTD ASP?")

        assert "164.22" in response.answer
        assert "2026-03-15" in response.answer
        assert "quarter-to-date" in response.answer
        assert [entry.tool for entry in response.trace] == ["get_qtd_estimate"]
        assert response.provider == "mock"
        assert response.prompt_version == PROMPT_VERSION

    @pytest.mark.anyio
    async def test_answers_a_historical_question(self, gateway: AiGateway) -> None:
        response = await gateway.answer("Show ACME total revenue history")

        assert [entry.tool for entry in response.trace] == ["get_kpi_estimates"]
        assert "historical" in response.answer
        assert "$MM" in response.answer

    @pytest.mark.anyio
    async def test_searches_then_retrieves_when_no_ticker_is_given(
        self, gateway: AiGateway
    ) -> None:
        response = await gateway.answer("what is the quarter-to-date asp for acme?")

        assert [entry.tool for entry in response.trace] == [
            "search_companies",
            "get_qtd_estimate",
        ]
        assert "164.22" in response.answer

    @pytest.mark.anyio
    async def test_recovers_from_a_recoverable_tool_error(self, gateway: AiGateway) -> None:
        response = await gateway.answer("SHIELD quarter-to-date units sold")

        # The first call is refused as ambiguous; the loop retries with the ticker
        # the tool suggested rather than guessing.
        statuses = [(entry.tool, entry.status, entry.error_code) for entry in response.trace]
        assert statuses == [
            ("get_qtd_estimate", "error", "ambiguous_company"),
            ("get_qtd_estimate", "ok", None),
        ]
        assert response.trace[1].arguments == {"ticker": "SHLD", "kpi": "Units Sold"}
        assert "ShieldNet" in response.answer

    @pytest.mark.anyio
    async def test_asks_which_company_when_several_match(self, gateway: AiGateway) -> None:
        response = await gateway.answer("cloud revenue")

        assert "Which one did you mean?" in response.answer
        assert [entry.tool for entry in response.trace] == ["search_companies"]

    @pytest.mark.anyio
    async def test_is_deterministic(self, gateway: AiGateway) -> None:
        first = await gateway.answer("What is ACME's QTD ASP?")
        second = await gateway.answer("What is ACME's QTD ASP?")

        assert first.answer == second.answer
        assert [e.tool for e in first.trace] == [e.tool for e in second.trace]
        assert first.request_id != second.request_id


class TestTrace:
    @pytest.mark.anyio
    async def test_is_ordered_and_carries_sanitized_arguments(self, gateway: AiGateway) -> None:
        response = await gateway.answer("what is the quarter-to-date asp for acme?")

        assert [entry.index for entry in response.trace] == [1, 2]
        assert response.trace[0].arguments == {"query": "acme"}
        assert response.trace[1].arguments == {"ticker": "ACME", "kpi": "ASP ($)"}
        assert all(entry.duration_ms >= 0 for entry in response.trace)

    @pytest.mark.anyio
    async def test_shares_one_correlation_id_with_the_audit_rows(
        self, gateway: AiGateway, session_factory: Callable[[], Session]
    ) -> None:
        response = await gateway.answer("what is the quarter-to-date asp for acme?")

        with session_factory() as session:
            records = list(session.scalars(select(McpToolCall).order_by(McpToolCall.id)))
        assert len(records) == len(response.trace)
        assert {record.correlation_id for record in records} == {response.request_id}

    @pytest.mark.anyio
    async def test_honours_a_caller_supplied_request_id(self, gateway: AiGateway) -> None:
        response = await gateway.answer("ACME QTD ASP", ChatContext(request_id="req-42"))

        assert response.request_id == "req-42"

    @pytest.mark.anyio
    async def test_accumulates_usage_across_iterations(self, gateway: AiGateway) -> None:
        response = await gateway.answer("what is the quarter-to-date asp for acme?")

        assert response.iterations == 3
        assert response.usage.input_tokens > 0
        assert response.usage.output_tokens > 0


class TestGuardrails:
    @pytest.mark.anyio
    async def test_stops_at_the_iteration_ceiling(self, tool_client: McpToolClient) -> None:
        # A provider that only ever asks for another tool call must not loop forever.
        provider = ScriptedProvider([_search_call()])
        gateway = AiGateway(
            provider, tool_client, GatewayLimits(max_tool_iterations=3, retry_backoff_seconds=0.0)
        )

        with pytest.raises(ToolIterationLimitError) as exc:
            await gateway.answer("anything")

        assert exc.value.code == "tool_loop_exhausted"
        assert provider.calls == 3

    @pytest.mark.anyio
    async def test_maps_a_slow_provider_call_to_a_timeout(self, tool_client: McpToolClient) -> None:
        class SlowProvider(ScriptedProvider):
            async def complete(
                self, system: str, turns: tuple[Turn, ...], tools: tuple[ToolSpec, ...]
            ) -> ProviderCompletion:
                await asyncio.sleep(1)
                raise AssertionError("the timeout should have fired first")

        gateway = AiGateway(
            SlowProvider([]),
            tool_client,
            GatewayLimits(call_timeout_seconds=0.01, retry_backoff_seconds=0.0),
        )

        with pytest.raises(GatewayTimeoutError) as exc:
            await gateway.answer("anything")

        assert exc.value.code == "timeout"

    @pytest.mark.anyio
    async def test_maps_an_exhausted_total_budget_to_a_timeout(
        self, tool_client: McpToolClient
    ) -> None:
        class SlowProvider(ScriptedProvider):
            async def complete(
                self, system: str, turns: tuple[Turn, ...], tools: tuple[ToolSpec, ...]
            ) -> ProviderCompletion:
                await asyncio.sleep(1)
                raise AssertionError("the timeout should have fired first")

        gateway = AiGateway(
            SlowProvider([]),
            tool_client,
            GatewayLimits(call_timeout_seconds=5.0, total_timeout_seconds=0.01),
        )

        with pytest.raises(GatewayTimeoutError):
            await gateway.answer("anything")

    @pytest.mark.anyio
    async def test_retries_a_transient_failure_then_succeeds(
        self, tool_client: McpToolClient
    ) -> None:
        provider = ScriptedProvider(
            [
                TransientProviderError("overloaded"),
                TransientProviderError("overloaded"),
                ProviderCompletion(text="recovered"),
            ]
        )
        gateway = AiGateway(
            provider, tool_client, GatewayLimits(max_retries=2, retry_backoff_seconds=0.0)
        )

        response = await gateway.answer("anything")

        assert response.answer == "recovered"
        assert provider.calls == 3

    @pytest.mark.anyio
    async def test_gives_up_after_the_retry_budget(self, tool_client: McpToolClient) -> None:
        provider = ScriptedProvider([TransientProviderError("overloaded")])
        gateway = AiGateway(
            provider, tool_client, GatewayLimits(max_retries=1, retry_backoff_seconds=0.0)
        )

        with pytest.raises(TransientProviderError):
            await gateway.answer("anything")

        assert provider.calls == 2

    @pytest.mark.anyio
    async def test_does_not_retry_a_permanent_provider_failure(
        self, tool_client: McpToolClient
    ) -> None:
        provider = ScriptedProvider([ProviderFailureError("bad request")])
        gateway = AiGateway(
            provider, tool_client, GatewayLimits(max_retries=3, retry_backoff_seconds=0.0)
        )

        with pytest.raises(ProviderFailureError):
            await gateway.answer("anything")

        assert provider.calls == 1

    @pytest.mark.anyio
    async def test_bounds_an_oversized_tool_result(self, server: MCPServer[Any]) -> None:
        client = McpToolClient(server, max_result_chars=50)

        outcome = await client.call("get_kpi_estimates", {"ticker": "ACME", "kpi": "ASP ($)"})

        assert outcome.truncated is True
        assert '"truncated": true' in outcome.payload


class TestProviderSelection:
    def test_defaults_to_the_mock_provider(self) -> None:
        provider = build_provider(Settings(llm_provider="mock", llm_model="mock-model"))

        assert provider.name == "mock"

    def test_rejects_an_unknown_provider(self) -> None:
        with pytest.raises(ProviderConfigurationError):
            build_provider(Settings(llm_provider="nope"))

    def test_refuses_a_live_provider_without_a_credential(self) -> None:
        # Proves the live path is unreachable by accident: no key, no provider,
        # and therefore no test can make a network call.
        with pytest.raises(ProviderConfigurationError):
            build_provider(Settings(llm_provider="anthropic", llm_api_key=None))


class TestQuestionUnderstanding:
    """Phrasings the brief uses, and the questions the planner must decline."""

    @pytest.mark.anyio
    async def test_answers_the_brief_example_question(self, gateway: AiGateway) -> None:
        # The example from the assignment, word for word.
        response = await gateway.answer("What's IGC's QTD subscriber growth this quarter?")

        assert [entry.tool for entry in response.trace] == ["get_qtd_estimate"]
        assert response.trace[0].arguments == {
            "ticker": "IGC",
            "kpi": "Global Net Added Subscribers",
        }
        assert "quarter-to-date" in response.answer
        assert "as of" in response.answer

    @pytest.mark.anyio
    @pytest.mark.parametrize(
        "question",
        [
            "ACME ASP this quarter",
            "ACME ASP right now",
            "what is ACME ASP currently",
            "ACME quarter-to-date ASP",
            "ACME ASP QTD",
        ],
    )
    async def test_recognizes_quarter_to_date_phrasings(
        self, gateway: AiGateway, question: str
    ) -> None:
        response = await gateway.answer(question)

        assert [entry.tool for entry in response.trace] == ["get_qtd_estimate"]

    @pytest.mark.anyio
    @pytest.mark.parametrize(
        ("question", "expected"),
        [
            ("IGC subscriber growth", "Global Net Added Subscribers"),
            ("IGC global subscribers", "Global Net Added Subscribers"),
            ("IGC U.S. subscribers", "U.S. Net Added Subscribers"),
            ("IGC us subscriber adds", "U.S. Net Added Subscribers"),
            ("IGC total revenue", "Total Revenue ($MM)"),
            ("IGC average selling price", "ASP ($)"),
            ("IGC units sold", "Units Sold"),
        ],
    )
    async def test_maps_kpi_wording_to_the_stored_name(
        self, gateway: AiGateway, question: str, expected: str
    ) -> None:
        response = await gateway.answer(question)

        assert response.trace[0].arguments["kpi"] == expected

    @pytest.mark.anyio
    async def test_honours_a_named_fiscal_period(self, gateway: AiGateway) -> None:
        response = await gateway.answer("What was ACME revenue in 2023Q2?")

        assert response.trace[0].tool == "get_kpi_estimates"
        assert response.trace[0].arguments["periods"] == ["2023Q2"]
        assert "2023Q2" in response.answer
        # The full history must not be dumped in place of the quarter asked for.
        assert "2025Q4" not in response.answer

    @pytest.mark.anyio
    async def test_honours_several_named_periods(self, gateway: AiGateway) -> None:
        response = await gateway.answer("ACME revenue for 2023Q1 and 2023Q2")

        assert response.trace[0].arguments["periods"] == ["2023Q1", "2023Q2"]

    @pytest.mark.anyio
    async def test_a_named_period_wins_over_quarter_to_date_wording(
        self, gateway: AiGateway
    ) -> None:
        # 2023Q2 is a closed quarter, so a QTD snapshot cannot answer it.
        response = await gateway.answer("ACME revenue in 2023Q2 quarter to date")

        assert response.trace[0].tool == "get_kpi_estimates"

    @pytest.mark.anyio
    async def test_reports_a_period_that_has_no_estimates(self, gateway: AiGateway) -> None:
        response = await gateway.answer("ACME revenue in 2030Q1")

        assert response.trace[0].arguments["periods"] == ["2030Q1"]
        assert response.trace[0].status == "error"
        assert response.trace[0].error_code == "no_data"
        # It must say there is nothing rather than show a different quarter.
        assert "No historical estimates" in response.answer
        assert "2025Q4" not in response.answer

    @pytest.mark.anyio
    @pytest.mark.parametrize(
        "question",
        [
            "Compare ACME and CLD9 revenue",
            "ACME versus CLD9 revenue",
            "what is the difference between ACME and CLD9 revenue",
            "ACME CLD9 revenue",
        ],
    )
    async def test_declines_a_multi_company_question(
        self, gateway: AiGateway, question: str
    ) -> None:
        response = await gateway.answer(question)

        # Answering for one company would read as an answer about both.
        assert response.trace == ()
        assert "one company at a time" in response.answer

    @pytest.mark.anyio
    async def test_a_single_company_question_is_not_mistaken_for_a_comparison(
        self, gateway: AiGateway
    ) -> None:
        response = await gateway.answer("What's IGC's QTD subscriber growth this quarter?")

        assert response.trace != ()
