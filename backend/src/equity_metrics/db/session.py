"""Engine and session construction.

A single engine per process is created lazily so importing the package never
opens a connection; tests and the CLI can supply their own database URL.
"""

from collections.abc import Iterator
from contextlib import contextmanager
from functools import lru_cache

from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import Session, sessionmaker

from equity_metrics.config import get_settings


def build_engine(database_url: str) -> Engine:
    """Create an engine for the given URL with pre-ping enabled."""
    return create_engine(database_url, pool_pre_ping=True, future=True)


@lru_cache
def get_engine() -> Engine:
    """Return the process-wide engine built from application settings."""
    return build_engine(get_settings().database_url)


def build_session_factory(engine: Engine) -> sessionmaker[Session]:
    """Create a session factory bound to the given engine."""
    return sessionmaker(bind=engine, expire_on_commit=False, future=True)


@contextmanager
def session_scope(engine: Engine | None = None) -> Iterator[Session]:
    """Yield a session that commits on success and rolls back on failure."""
    factory = build_session_factory(engine or get_engine())
    session = factory()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
