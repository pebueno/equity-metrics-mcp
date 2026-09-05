"""MCP server construction and the local stdio entry point.

The server is the authoritative data interface: it holds no queries of its own
and reaches PostgreSQL only through the shared KPI services.

`mcp` 2.x renamed `FastMCP` to `MCPServer`; this is the same decorator-based
server the project targets, on the current major version of the official SDK.
"""

import logging
from collections.abc import Callable
from typing import Any

from mcp.server.mcpserver import MCPServer
from sqlalchemy.orm import Session

from equity_metrics.config import get_settings
from equity_metrics.db.session import build_engine, build_session_factory
from equity_metrics.mcp_server.tools import register_tools

INSTRUCTIONS = """\
Serves curated quarterly KPI estimates for public companies from a fixed
dataset. Every value comes from the database: never invent a company, KPI,
period, value, unit, or as_of date, and never convert units yourself.

Resolve a company with search_companies when the name is approximate, then use
the exact ticker it returns. Historical estimates and quarter-to-date snapshots
are different things: label them as such, and always report the as_of date of a
QTD snapshot. If a tool result has isError, read its code and suggestions and
retry with a corrected argument rather than guessing.
"""


def create_server(session_factory: Callable[[], Session] | None = None) -> MCPServer[Any]:
    """Build the MCP server, optionally over an injected session factory."""
    factory = session_factory or build_session_factory(build_engine(get_settings().database_url))
    server: MCPServer[Any] = MCPServer(
        name="equity-metrics",
        version="0.1.0",
        instructions=INSTRUCTIONS,
    )
    register_tools(server, factory)
    return server


def main() -> None:
    """Run the server over stdio for a local MCP client."""
    settings = get_settings()
    # stdout carries the protocol, so logs must go to stderr only.
    logging.basicConfig(level=settings.log_level, format="%(levelname)s %(name)s %(message)s")
    create_server().run(transport="stdio")


if __name__ == "__main__":  # pragma: no cover
    main()
