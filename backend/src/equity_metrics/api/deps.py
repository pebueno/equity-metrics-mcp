"""Request-scoped dependencies for the HTTP API.

Both dependencies read what `create_app` put on application state, so an app
built from one Settings object never reaches another one's database.
"""

from collections.abc import Iterator

from fastapi import Request
from sqlalchemy.orm import Session

from equity_metrics.ai_gateway.gateway import AiGateway


def get_session(request: Request) -> Iterator[Session]:
    """Yield a read-only-by-convention session for the lifetime of one request."""
    session = request.app.state.session_factory()
    try:
        yield session
    finally:
        session.close()


def get_gateway(request: Request) -> AiGateway:
    """Return the process-wide gateway built for this application."""
    gateway: AiGateway = request.app.state.gateway
    return gateway
