"""MCP tool behavior: output shape, recoverable errors, and the audit trail."""

from collections.abc import Callable, Iterator
from typing import Any

import pytest
from mcp.server.mcpserver import MCPServer
from mcp.types import CallToolResult
from sqlalchemy import Engine, select
from sqlalchemy.orm import Session, sessionmaker

from equity_metrics.db.models import McpToolCall
from equity_metrics.mcp_server.audit import correlation_scope, sanitize_arguments
from equity_metrics.mcp_server.server import create_server

EXPECTED_TOOLS = {
    "search_companies",
    "list_company_kpis",
    "get_kpi_estimates",
    "get_qtd_estimate",
}


@pytest.fixture
def session_factory(seeded_session: Session, engine: Engine) -> Callable[[], Session]:
    """Build sessions over the seeded test database."""
    return sessionmaker(bind=engine, expire_on_commit=False)


@pytest.fixture
def server(session_factory: Callable[[], Session]) -> Iterator[MCPServer[Any]]:
    """Serve the tools over the seeded database with an empty audit table."""
    with session_factory() as session:
        session.query(McpToolCall).delete()
        session.commit()
    yield create_server(session_factory)


def audit_records(session_factory: Callable[[], Session]) -> list[McpToolCall]:
    with session_factory() as session:
        return list(session.scalars(select(McpToolCall).order_by(McpToolCall.id)))


async def call(server: MCPServer[Any], name: str, arguments: dict[str, Any]) -> CallToolResult:
    return await server.call_tool(name, arguments)


@pytest.mark.anyio
async def test_exposes_exactly_the_documented_tools(server: MCPServer[Any]) -> None:
    tools = await server.list_tools()

    assert {tool.name for tool in tools} == EXPECTED_TOOLS
    # Each tool must describe itself well enough for an agent to choose it.
    assert all(tool.description for tool in tools)


@pytest.mark.anyio
async def test_search_companies_returns_candidates(server: MCPServer[Any]) -> None:
    result = await call(server, "search_companies", {"query": "cloud"})

    assert result.is_error is False
    assert result.structured_content is not None
    assert [company["ticker"] for company in result.structured_content["companies"]] == [
        "CLD9",
        "STRT",
    ]


@pytest.mark.anyio
async def test_search_companies_narrows_by_sector(server: MCPServer[Any]) -> None:
    result = await call(server, "search_companies", {"query": "", "sector": "Cloud"})

    assert result.structured_content is not None
    assert len(result.structured_content["companies"]) == 3


@pytest.mark.anyio
async def test_list_company_kpis_returns_names_and_units(server: MCPServer[Any]) -> None:
    result = await call(server, "list_company_kpis", {"ticker_or_company": "acme"})

    assert result.structured_content is not None
    body = result.structured_content
    assert body["company"]["ticker"] == "ACME"
    assert {"kpi": "ASP ($)", "unit": "$"} in body["kpis"]


@pytest.mark.anyio
async def test_get_kpi_estimates_returns_chronological_history(server: MCPServer[Any]) -> None:
    result = await call(server, "get_kpi_estimates", {"ticker": "ACME", "kpi": "ASP ($)"})

    assert result.structured_content is not None
    estimates = result.structured_content["estimates"]
    assert [point["period"] for point in estimates] == sorted(
        point["period"] for point in estimates
    )
    assert estimates[0]["unit"] == "$"


@pytest.mark.anyio
async def test_get_kpi_estimates_accepts_a_period_filter(server: MCPServer[Any]) -> None:
    result = await call(
        server,
        "get_kpi_estimates",
        {"ticker": "ACME", "kpi": "ASP ($)", "periods": ["2022Q1", "2022Q2"]},
    )

    assert result.structured_content is not None
    assert [p["period"] for p in result.structured_content["estimates"]] == ["2022Q1", "2022Q2"]


@pytest.mark.anyio
async def test_get_qtd_estimate_returns_the_latest_snapshot(server: MCPServer[Any]) -> None:
    result = await call(server, "get_qtd_estimate", {"ticker": "ACME", "kpi": "ASP ($)"})

    assert result.structured_content is not None
    body = result.structured_content
    assert body["as_of"] == "2026-03-15"
    assert body["value"] == "164.22"
    assert body["unit"] == "$"
    assert body["period"] == "2026Q1"


@pytest.mark.anyio
async def test_unknown_company_is_a_recoverable_tool_error(server: MCPServer[Any]) -> None:
    result = await call(server, "list_company_kpis", {"ticker_or_company": "Nonexistent"})

    assert result.is_error is True
    assert result.structured_content is not None
    body = result.structured_content
    assert body["isError"] is True
    assert body["error"]["code"] == "unknown_company"
    assert body["error"]["normalized_query"] == "Nonexistent"


@pytest.mark.anyio
async def test_ambiguous_company_suggests_tickers(server: MCPServer[Any]) -> None:
    result = await call(server, "get_qtd_estimate", {"ticker": "Cloud", "kpi": "ASP ($)"})

    assert result.is_error is True
    assert result.structured_content is not None
    error = result.structured_content["error"]
    assert error["code"] == "ambiguous_company"
    assert [s["value"] for s in error["suggestions"]] == ["CLD9", "STRT"]


@pytest.mark.anyio
async def test_unknown_kpi_suggests_available_kpis(server: MCPServer[Any]) -> None:
    result = await call(server, "get_qtd_estimate", {"ticker": "ACME", "kpi": "EBITDA"})

    assert result.is_error is True
    assert result.structured_content is not None
    error = result.structured_content["error"]
    assert error["code"] == "unknown_kpi"
    assert len(error["suggestions"]) == 5


@pytest.mark.anyio
async def test_invalid_period_is_reported_with_its_code(server: MCPServer[Any]) -> None:
    result = await call(
        server, "get_kpi_estimates", {"ticker": "ACME", "kpi": "ASP ($)", "periods": ["2022Q9"]}
    )

    assert result.is_error is True
    assert result.structured_content is not None
    assert result.structured_content["error"]["code"] == "invalid_period"


@pytest.mark.anyio
async def test_the_error_payload_is_also_readable_as_text(server: MCPServer[Any]) -> None:
    result = await call(server, "list_company_kpis", {"ticker_or_company": "Nonexistent"})

    assert "unknown_company" in "".join(
        block.text for block in result.content if block.type == "text"
    )


@pytest.mark.anyio
async def test_a_successful_call_is_audited(
    server: MCPServer[Any], session_factory: Callable[[], Session]
) -> None:
    await call(server, "get_qtd_estimate", {"ticker": "ACME", "kpi": "ASP ($)"})

    record = audit_records(session_factory)[0]
    assert record.tool_name == "get_qtd_estimate"
    assert record.outcome == "success"
    assert record.error_code is None
    assert record.sanitized_arguments == {"ticker": "ACME", "kpi": "ASP ($)"}
    assert record.duration_ms >= 0
    assert record.correlation_id


@pytest.mark.anyio
async def test_a_failed_call_is_audited_with_its_error_code(
    server: MCPServer[Any], session_factory: Callable[[], Session]
) -> None:
    await call(server, "list_company_kpis", {"ticker_or_company": "Nonexistent"})

    record = audit_records(session_factory)[0]
    assert record.outcome == "error"
    assert record.error_code == "unknown_company"


@pytest.mark.anyio
async def test_calls_in_one_correlation_scope_share_an_id(
    server: MCPServer[Any], session_factory: Callable[[], Session]
) -> None:
    with correlation_scope("req-123"):
        await call(server, "search_companies", {"query": "acme"})
        await call(server, "get_qtd_estimate", {"ticker": "ACME", "kpi": "ASP ($)"})

    records = audit_records(session_factory)
    assert [record.correlation_id for record in records] == ["req-123", "req-123"]


@pytest.mark.anyio
async def test_unscoped_calls_get_distinct_correlation_ids(
    server: MCPServer[Any], session_factory: Callable[[], Session]
) -> None:
    await call(server, "search_companies", {"query": "acme"})
    await call(server, "search_companies", {"query": "cloud"})

    records = audit_records(session_factory)
    assert records[0].correlation_id != records[1].correlation_id


@pytest.mark.anyio
async def test_omitted_optional_arguments_are_not_audited(
    server: MCPServer[Any], session_factory: Callable[[], Session]
) -> None:
    await call(server, "search_companies", {"query": "acme"})

    assert audit_records(session_factory)[0].sanitized_arguments == {"query": "acme"}


class TestArgumentSanitization:
    def test_redacts_credential_and_prompt_bearing_keys(self) -> None:
        sanitized = sanitize_arguments(
            {"api_key": "sk-secret", "prompt": "the full user question", "ticker": "ACME"}
        )

        assert sanitized == {
            "api_key": "[redacted]",
            "prompt": "[redacted]",
            "ticker": "ACME",
        }

    def test_bounds_long_values_and_long_lists(self) -> None:
        sanitized = sanitize_arguments({"query": "x" * 500, "periods": ["2024Q1"] * 50})

        assert len(sanitized["query"]) == 200
        assert len(sanitized["periods"]) == 20

    def test_drops_none_values(self) -> None:
        assert sanitize_arguments({"query": "acme", "sector": None}) == {"query": "acme"}
