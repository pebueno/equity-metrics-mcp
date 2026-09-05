"""End-to-end paths through the real composition.

These tests build the application from Settings, exactly as the process does,
and override nothing. What they exercise is the full chain: HTTP -> gateway ->
mock provider -> MCP tools -> shared services -> PostgreSQL, and back out
through the audit trail.
"""

import os
from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, select
from sqlalchemy.orm import Session

from equity_metrics.api.main import create_app
from equity_metrics.config import Settings
from equity_metrics.db.models import McpToolCall

from .conftest import DEFAULT_TEST_DATABASE_URL


@pytest.fixture
def settings(engine: Engine) -> Settings:
    """Point a real Settings object at the test database."""
    return Settings(
        app_env="test",
        llm_provider="mock",
        llm_model="mock-model",
        database_url=os.environ.get("TEST_DATABASE_URL", DEFAULT_TEST_DATABASE_URL),
    )


@pytest.fixture
def client(settings: Settings, seeded_session: Session) -> Iterator[TestClient]:
    with TestClient(create_app(settings)) as test_client:
        yield test_client


@pytest.fixture
def audit(seeded_session: Session) -> Iterator[Session]:
    seeded_session.query(McpToolCall).delete()
    seeded_session.commit()
    yield seeded_session


def audited(session: Session) -> list[McpToolCall]:
    session.expire_all()
    return list(session.scalars(select(McpToolCall).order_by(McpToolCall.id)))


def test_the_stack_is_healthy(client: TestClient) -> None:
    assert client.get("/api/health").json() == {"status": "ok", "app_env": "test"}


def test_a_question_travels_the_whole_stack(client: TestClient, audit: Session) -> None:
    response = client.post("/api/chat", json={"question": "ACME quarter-to-date ASP"})

    assert response.status_code == 200
    body = response.json()

    # The answer only repeats what the database holds.
    assert "164.22" in body["answer"]
    assert "2026-03-15" in body["answer"]
    assert body["data"][0]["data"]["value"] == "164.22"

    # The visible trace and the persisted audit trail agree, call for call.
    records = audited(audit)
    assert [record.tool_name for record in records] == [entry["tool"] for entry in body["trace"]]
    assert {record.correlation_id for record in records} == {body["request_id"]}
    assert [record.outcome for record in records] == ["success"]


def test_a_recoverable_failure_is_answered_and_audited(client: TestClient, audit: Session) -> None:
    response = client.post("/api/chat", json={"question": "SHIELD quarter-to-date units sold"})

    assert response.status_code == 200
    body = response.json()
    assert "ShieldNet" in body["answer"]

    trace = body["trace"]
    assert [entry["status"] for entry in trace] == ["error", "ok"]
    assert trace[0]["error_code"] == "ambiguous_company"

    records = audited(audit)
    assert [(r.outcome, r.error_code) for r in records] == [
        ("error", "ambiguous_company"),
        ("success", None),
    ]


def test_an_unresolvable_question_is_answered_without_inventing_data(
    client: TestClient, audit: Session
) -> None:
    response = client.post("/api/chat", json={"question": "Nonexistent Holdings revenue"})

    assert response.status_code == 200
    body = response.json()
    assert "No company matched" in body["answer"]
    # The search succeeded and found nothing; that is data, not a failure, and
    # the answer says so instead of naming a company.
    assert body["data"][0]["data"]["companies"] == []
    assert [record.outcome for record in audited(audit)] == ["success"]


def test_the_rest_endpoints_read_the_same_database(client: TestClient) -> None:
    kpis = client.get("/api/companies/ACME/kpis")
    qtd = client.get("/api/companies/ACME/kpis/ASP ($)/qtd")

    assert kpis.status_code == 200
    assert qtd.json()["value"] == "164.22"


def test_an_unknown_company_is_a_structured_http_error(client: TestClient) -> None:
    response = client.get("/api/companies/Nonexistent Holdings/kpis")

    assert response.status_code == 404
    assert response.json()["code"] == "unknown_company"
