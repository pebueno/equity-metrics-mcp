"""HTTP contract of the KPI endpoints, including recoverable error responses."""

from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from equity_metrics.api.deps import get_session
from equity_metrics.api.main import create_app
from equity_metrics.config import Settings


@pytest.fixture
def client(seeded_session: Session) -> Iterator[TestClient]:
    """Serve the API against the seeded test database."""
    app = create_app(Settings(app_env="test"))
    app.dependency_overrides[get_session] = lambda: seeded_session
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


def test_lists_sectors(client: TestClient) -> None:
    response = client.get("/api/sectors")

    assert response.status_code == 200
    assert {"sector": "Cloud", "company_count": 3} in response.json()


def test_searches_companies(client: TestClient) -> None:
    response = client.get("/api/companies", params={"query": "cloud"})

    assert response.status_code == 200
    body = response.json()
    assert body["query"] == "cloud"
    assert [company["ticker"] for company in body["companies"]] == ["CLD9", "STRT"]


def test_rejects_an_out_of_range_limit(client: TestClient) -> None:
    assert client.get("/api/companies", params={"limit": 500}).status_code == 422


def test_lists_company_kpis(client: TestClient) -> None:
    response = client.get("/api/companies/acme/kpis")

    assert response.status_code == 200
    body = response.json()
    assert body["company"] == {
        "ticker": "ACME",
        "company_name": "Acme E-commerce",
        "sector": "E-commerce",
    }
    assert {"kpi": "ASP ($)", "unit": "$"} in body["kpis"]


def test_returns_historical_estimates_in_order_with_units(client: TestClient) -> None:
    response = client.get("/api/companies/ACME/kpis/ASP ($)/estimates")

    assert response.status_code == 200
    body = response.json()
    assert body["unit"] == "$"
    periods = [point["period"] for point in body["estimates"]]
    assert periods == sorted(periods)
    # Values keep exact precision and never travel without their unit.
    assert body["estimates"][0] == {
        "period": "2022Q1",
        "period_start": "2022-01-01",
        "period_end": "2022-03-31",
        "value": "128.67",
        "unit": "$",
    }


def test_filters_estimates_by_period(client: TestClient) -> None:
    response = client.get(
        "/api/companies/ACME/kpis/ASP ($)/estimates", params={"periods": ["2022Q1", "2022Q2"]}
    )

    assert [point["period"] for point in response.json()["estimates"]] == ["2022Q1", "2022Q2"]


def test_returns_the_latest_qtd_snapshot(client: TestClient) -> None:
    response = client.get("/api/companies/ACME/kpis/ASP ($)/qtd")

    assert response.status_code == 200
    body = response.json()
    assert body["as_of"] == "2026-03-15"
    assert body["value"] == "164.22"
    assert body["period"] == "2026Q1"
    assert body["unit"] == "$"


def test_unknown_company_returns_404_with_a_machine_readable_code(client: TestClient) -> None:
    response = client.get("/api/companies/Nonexistent Holdings/kpis")

    assert response.status_code == 404
    assert response.json() == {
        "code": "unknown_company",
        "message": "No company matches 'Nonexistent Holdings'.",
        "normalized_query": "Nonexistent Holdings",
        "suggestions": [],
    }


def test_ambiguous_company_returns_409_with_suggestions(client: TestClient) -> None:
    response = client.get("/api/companies/Cloud/kpis")

    assert response.status_code == 409
    body = response.json()
    assert body["code"] == "ambiguous_company"
    assert [suggestion["value"] for suggestion in body["suggestions"]] == ["CLD9", "STRT"]


def test_unknown_kpi_returns_404_with_available_kpis(client: TestClient) -> None:
    response = client.get("/api/companies/ACME/kpis/EBITDA/qtd")

    assert response.status_code == 404
    body = response.json()
    assert body["code"] == "unknown_kpi"
    assert len(body["suggestions"]) == 5


def test_invalid_period_returns_400(client: TestClient) -> None:
    response = client.get(
        "/api/companies/ACME/kpis/ASP ($)/estimates", params={"periods": ["2022Q9"]}
    )

    assert response.status_code == 400
    assert response.json()["code"] == "invalid_period"
