"""FastAPI application factory and process-level entry point."""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from equity_metrics.config import Settings, get_settings


class HealthResponse(BaseModel):
    """Liveness payload used by Docker Compose and local smoke checks."""

    status: str
    app_env: str


def create_app(settings: Settings | None = None) -> FastAPI:
    """Build the API application; accepts settings so tests can override them."""
    resolved = settings or get_settings()
    app = FastAPI(title="EquityMetrics MCP", version="0.1.0")
    app.add_middleware(
        CORSMiddleware,
        allow_origins=list(resolved.cors_allow_origins),
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.get("/api/health", response_model=HealthResponse)
    def health() -> HealthResponse:
        return HealthResponse(status="ok", app_env=resolved.app_env)

    return app


app = create_app()
