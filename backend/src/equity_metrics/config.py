"""Application settings loaded from the environment.

Every runtime knob lives here so a fresh clone can discover the full
environment contract from `.env.example` and this module alone.
"""

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Environment-backed configuration for the API, importer, and MCP server."""

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_env: str = "local"
    log_level: str = "INFO"

    database_url: str = "postgresql+psycopg://equity:equity@localhost:5432/equity_metrics"

    # `mock` keeps the whole stack runnable and testable without credentials.
    llm_provider: str = "mock"
    llm_model: str = "mock-model"
    llm_api_key: str | None = None
    # Per-provider-call timeout; the whole answer has its own larger budget.
    llm_timeout_seconds: float = 30.0
    llm_total_timeout_seconds: float = 90.0
    llm_max_tool_iterations: int = 6
    llm_max_retries: int = 2

    cors_allow_origins: tuple[str, ...] = ("http://localhost:5173",)


@lru_cache
def get_settings() -> Settings:
    """Return process-wide settings, cached so env parsing happens once."""
    return Settings()
