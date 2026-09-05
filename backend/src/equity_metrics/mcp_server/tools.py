"""The MCP tool surface over the shared KPI services.

Four tools cover the natural LLM workflow: find a company, see what it reports,
read its history, then read its current quarter. Each one delegates to
`kpi_service`, so tools and the HTTP API share validation and retrieval.

Recoverable business failures come back as tool results with `isError` set and
a machine-readable code, never as protocol errors, so an agent can correct the
call and retry without a transport-level failure.
"""

import json
from collections.abc import Callable
from dataclasses import asdict
from typing import Any, cast

from mcp.server.mcpserver import MCPServer
from mcp.types import CallToolResult, TextContent
from sqlalchemy.orm import Session

from equity_metrics.domain.errors import DomainError, to_payload
from equity_metrics.mcp_server.audit import audit_tool_call
from equity_metrics.services import kpi_service

SessionFactory = Callable[[], Session]
ToolResult = dict[str, Any]


def register_tools(server: MCPServer[Any], session_factory: SessionFactory) -> None:
    """Register every tool on the given server, bound to a session factory."""

    @server.tool()
    def search_companies(query: str, sector: str | None = None) -> ToolResult:
        """Find companies by name or ticker, optionally narrowed to a sector.

        Returns bounded candidates with the canonical company name, ticker, and
        sector. Use this first when the investor names a company loosely.
        """
        return _run(
            "search_companies",
            {"query": query, "sector": sector},
            session_factory,
            lambda session: kpi_service.search_companies(
                session, query=query, sector=sector
            ).model_dump(mode="json"),
        )

    @server.tool()
    def list_company_kpis(ticker_or_company: str) -> ToolResult:
        """List the KPIs a company reports, with the unit of each.

        Accepts a ticker or an exact company name. Call this before requesting
        estimates so the KPI name is exact.
        """
        return _run(
            "list_company_kpis",
            {"ticker_or_company": ticker_or_company},
            session_factory,
            lambda session: kpi_service.list_company_kpis(session, ticker_or_company).model_dump(
                mode="json"
            ),
        )

    @server.tool()
    def get_kpi_estimates(ticker: str, kpi: str, periods: list[str] | None = None) -> ToolResult:
        """Return historical KPI estimates in chronological order.

        Omit `periods` for the full history. Supply fiscal period labels such as
        ["2024Q3", "2024Q4"] to narrow the result. Values are historical, not
        quarter-to-date; use get_qtd_estimate for the current quarter.
        """
        return _run(
            "get_kpi_estimates",
            {"ticker": ticker, "kpi": kpi, "periods": periods},
            session_factory,
            lambda session: kpi_service.get_historical_estimates(
                session, company_query=ticker, kpi_query=kpi, periods=periods
            ).model_dump(mode="json"),
        )

    @server.tool()
    def get_qtd_estimate(ticker: str, kpi: str) -> ToolResult:
        """Return the most recent quarter-to-date snapshot for a company KPI.

        The snapshot is the one with the latest `as_of` date, which is not
        necessarily the largest value. Always report `as_of` alongside the
        value so the reader knows how current it is.
        """
        return _run(
            "get_qtd_estimate",
            {"ticker": ticker, "kpi": kpi},
            session_factory,
            lambda session: kpi_service.get_latest_qtd_estimate(
                session, company_query=ticker, kpi_query=kpi
            ).model_dump(mode="json"),
        )


def _run(
    tool_name: str,
    arguments: dict[str, Any],
    session_factory: SessionFactory,
    operation: Callable[[Session], ToolResult],
) -> ToolResult:
    """Execute one tool call: audit it, and convert domain errors to results."""
    with audit_tool_call(tool_name, arguments, session_factory) as record:
        try:
            with session_factory() as session:
                return operation(session)
        except DomainError as error:
            record.mark_error(error.code)
            return _error_result(error)


def _error_result(error: DomainError) -> ToolResult:
    """Render a recoverable domain error as an MCP tool result.

    Tools are annotated as returning a dict because that is what drives their
    published output schema. The SDK also accepts a `CallToolResult`, which is
    the only way to set the protocol `isError` flag on a successful call, so the
    error path returns one and casts back to the declared type.
    """
    payload = {"isError": True, "error": asdict(to_payload(error))}
    # The text block repeats the payload so clients that read only text still
    # receive the code and the suggestions.
    result = CallToolResult(
        content=[TextContent(type="text", text=json.dumps(payload))],
        structured_content=payload,
        is_error=True,
    )
    return cast(ToolResult, result)
