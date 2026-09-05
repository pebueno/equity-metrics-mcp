"""The chat endpoint contract, served from a gateway wired to the test database."""

from collections.abc import Callable, Iterator
from typing import Any

import pytest
from fastapi.testclient import TestClient
from mcp.server.mcpserver import MCPServer
from sqlalchemy import Engine
from sqlalchemy.orm import Session, sessionmaker

from equity_metrics.ai_gateway.contracts import ProviderCompletion, ToolSpec, Turn
from equity_metrics.ai_gateway.errors import GatewayTimeoutError
from equity_metrics.ai_gateway.gateway import AiGateway, GatewayLimits
from equity_metrics.ai_gateway.providers.mock import MockProvider
from equity_metrics.ai_gateway.tool_client import McpToolClient
from equity_metrics.api.chat import get_gateway
from equity_metrics.api.main import create_app
from equity_metrics.config import Settings
from equity_metrics.db.models import McpToolCall
from equity_metrics.mcp_server.server import create_server


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
def gateway(server: MCPServer[Any]) -> AiGateway:
    return AiGateway(
        MockProvider(), McpToolClient(server), GatewayLimits(retry_backoff_seconds=0.0)
    )


def build_client(gateway: AiGateway) -> TestClient:
    app = create_app(Settings(app_env="test"))
    app.dependency_overrides[get_gateway] = lambda: gateway
    return TestClient(app)


@pytest.fixture
def client(gateway: AiGateway) -> Iterator[TestClient]:
    with build_client(gateway) as test_client:
        yield test_client


def test_answers_a_question_with_its_tool_trace(client: TestClient) -> None:
    response = client.post("/api/chat", json={"question": "What is ACME's QTD ASP?"})

    assert response.status_code == 200
    body = response.json()
    assert "164.22" in body["answer"]
    assert "2026-03-15" in body["answer"]
    assert body["provider"] == "mock"
    assert body["prompt_version"] == "v1"
    assert body["request_id"]
    assert body["trace"] == [
        {
            "index": 1,
            "tool": "get_qtd_estimate",
            "arguments": {"ticker": "ACME", "kpi": "ASP ($)"},
            "status": "ok",
            "duration_ms": body["trace"][0]["duration_ms"],
            "error_code": None,
            "truncated": False,
        }
    ]


def test_returns_the_structured_data_behind_the_answer(client: TestClient) -> None:
    response = client.post("/api/chat", json={"question": "What is ACME's QTD ASP?"})

    data = response.json()["data"]
    assert [item["tool"] for item in data] == ["get_qtd_estimate"]
    # The table the reader sees comes from the same call as the sentence.
    assert data[0]["data"]["value"] == "164.22"
    assert data[0]["data"]["as_of"] == "2026-03-15"
    assert data[0]["data"]["unit"] == "$"


def test_omits_failed_tool_calls_from_the_data(client: TestClient) -> None:
    response = client.post("/api/chat", json={"question": "SHIELD quarter-to-date units sold"})

    body = response.json()
    assert len(body["trace"]) == 2
    assert [item["tool"] for item in body["data"]] == ["get_qtd_estimate"]
    assert body["data"][0]["data"]["company"]["ticker"] == "SHLD"


def test_trace_is_ordered_and_reports_recoverable_tool_errors(client: TestClient) -> None:
    response = client.post("/api/chat", json={"question": "SHIELD quarter-to-date units sold"})

    trace = response.json()["trace"]
    assert [entry["index"] for entry in trace] == [1, 2]
    assert trace[0]["status"] == "error"
    assert trace[0]["error_code"] == "ambiguous_company"
    assert trace[1]["status"] == "ok"


def test_rejects_an_empty_question(client: TestClient) -> None:
    assert client.post("/api/chat", json={"question": ""}).status_code == 422


def test_rejects_an_oversized_question(client: TestClient) -> None:
    assert client.post("/api/chat", json={"question": "x" * 501}).status_code == 422


def test_reports_a_gateway_timeout_as_service_unavailable(server: MCPServer[Any]) -> None:
    class SlowProvider(MockProvider):
        async def complete(
            self, system: str, turns: tuple[Turn, ...], tools: tuple[ToolSpec, ...]
        ) -> ProviderCompletion:
            raise GatewayTimeoutError("too slow")

    gateway = AiGateway(SlowProvider(), McpToolClient(server), GatewayLimits())
    with build_client(gateway) as client:
        response = client.post("/api/chat", json={"question": "anything"})

    assert response.status_code == 503
    assert response.json()["detail"] == {"code": "timeout", "message": "too slow"}
