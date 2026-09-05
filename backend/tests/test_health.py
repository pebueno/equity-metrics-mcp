from fastapi.testclient import TestClient

from equity_metrics.api.main import create_app
from equity_metrics.config import Settings


def test_health_reports_configured_environment() -> None:
    client = TestClient(create_app(Settings(app_env="test")))

    response = client.get("/api/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "app_env": "test"}
