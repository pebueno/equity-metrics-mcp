"""Shared fixtures.

Database tests run against a real PostgreSQL instance because the schema relies
on PostgreSQL-specific behavior (JSONB, partial and NULLS NOT DISTINCT indexes,
ON CONFLICT). They skip with an actionable message when no server is reachable.
"""

import os
from collections.abc import Iterator
from pathlib import Path

import pytest
from sqlalchemy import Engine, create_engine, text
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

from equity_metrics.db.base import Base
from equity_metrics.db.models import Company, Estimate, KpiDefinition, McpToolCall, Sector
from equity_metrics.importer.csv_import import import_csv

DEFAULT_TEST_DATABASE_URL = "postgresql+psycopg://equity:equity@localhost:5432/equity_metrics_test"
SKIP_REASON = (
    "PostgreSQL is not reachable. Start it with `docker compose up -d db`, or set "
    "TEST_DATABASE_URL to point at another server."
)

REPO_ROOT = Path(__file__).resolve().parents[2]
SAMPLE_CSV = REPO_ROOT / "kpi_sample_2000__282_29__281_29.csv"
EXPECTED_ESTIMATE_COUNT = 2000


@pytest.fixture(scope="session")
def anyio_backend() -> str:
    """Run async tests on asyncio only; the MCP server needs no second backend."""
    return "asyncio"


@pytest.fixture(scope="session")
def engine() -> Iterator[Engine]:
    """Create the test database and schema once per test session."""
    url = os.environ.get("TEST_DATABASE_URL", DEFAULT_TEST_DATABASE_URL)
    try:
        _ensure_database_exists(url)
    except OperationalError:
        pytest.skip(SKIP_REASON)

    test_engine = create_engine(url, pool_pre_ping=True, future=True)
    Base.metadata.create_all(test_engine)
    yield test_engine
    test_engine.dispose()


@pytest.fixture
def session(engine: Engine) -> Iterator[Session]:
    """Yield a session over an empty database; every test starts from a clean slate."""
    with Session(engine, expire_on_commit=False) as db_session:
        for model in (Estimate, McpToolCall, Company, KpiDefinition, Sector):
            db_session.query(model).delete()
        db_session.commit()
        yield db_session


def _ensure_database_exists(url: str) -> None:
    """Create the target database if the server is up but the database is missing."""
    target = create_engine(url, connect_args={"connect_timeout": 3})
    try:
        with target.connect():
            return
    except OperationalError as exc:
        if "does not exist" not in str(exc):
            raise
    finally:
        target.dispose()

    database_name = url.rsplit("/", 1)[-1]
    admin = create_engine(
        url.rsplit("/", 1)[0] + "/postgres",
        isolation_level="AUTOCOMMIT",
        connect_args={"connect_timeout": 3},
    )
    try:
        with admin.connect() as connection:
            connection.execute(text(f'CREATE DATABASE "{database_name}"'))
    finally:
        admin.dispose()


@pytest.fixture
def seeded_session(engine: Engine) -> Iterator[Session]:
    """Yield a session over the imported sample dataset.

    The data is re-imported only when a previous test emptied the database, so
    read-only suites pay the import cost at most once.
    """
    with Session(engine, expire_on_commit=False) as db_session:
        if db_session.query(Estimate).count() != EXPECTED_ESTIMATE_COUNT:
            for model in (Estimate, Company, KpiDefinition, Sector):
                db_session.query(model).delete()
            db_session.commit()
            import_csv(SAMPLE_CSV, db_session)
            db_session.commit()
        yield db_session
