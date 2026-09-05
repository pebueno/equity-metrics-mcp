"""Request-scoped dependencies for the HTTP API."""

from collections.abc import Iterator

from sqlalchemy.orm import Session

from equity_metrics.db.session import build_session_factory, get_engine


def get_session() -> Iterator[Session]:
    """Yield a read-only-by-convention session for the lifetime of one request."""
    factory = build_session_factory(get_engine())
    session = factory()
    try:
        yield session
    finally:
        session.close()
