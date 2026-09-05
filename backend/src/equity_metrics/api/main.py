"""FastAPI application factory and process-level entry point."""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from equity_metrics.api.chat import router as chat_router
from equity_metrics.api.errors import register_error_handlers
from equity_metrics.api.routes import router
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

    register_error_handlers(app)
    app.include_router(router)
    app.include_router(chat_router)
    return app


app = create_app()
