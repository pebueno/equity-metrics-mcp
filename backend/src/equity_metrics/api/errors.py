"""Mapping from recoverable domain errors to HTTP responses.

The response body is the same payload the MCP tools return, so a client sees
one error vocabulary regardless of which interface produced it.
"""

from dataclasses import asdict

from fastapi import FastAPI, Request, status
from fastapi.responses import JSONResponse

from equity_metrics.domain.errors import (
    AmbiguousCompanyError,
    AmbiguousKpiError,
    DomainError,
    InvalidPeriodError,
    NoDataError,
    UnknownCompanyError,
    UnknownKpiError,
    to_payload,
)

# 409 marks input that resembles several known entities: the caller must choose,
# because resolving it here would mean guessing.
STATUS_BY_ERROR: dict[type[DomainError], int] = {
    UnknownCompanyError: status.HTTP_404_NOT_FOUND,
    UnknownKpiError: status.HTTP_404_NOT_FOUND,
    NoDataError: status.HTTP_404_NOT_FOUND,
    AmbiguousCompanyError: status.HTTP_409_CONFLICT,
    AmbiguousKpiError: status.HTTP_409_CONFLICT,
    InvalidPeriodError: status.HTTP_400_BAD_REQUEST,
}


def register_error_handlers(app: FastAPI) -> None:
    """Install the domain error handler on the application."""

    @app.exception_handler(DomainError)
    async def handle_domain_error(_: Request, exc: Exception) -> JSONResponse:
        if not isinstance(exc, DomainError):
            raise exc
        http_status = STATUS_BY_ERROR.get(type(exc), status.HTTP_400_BAD_REQUEST)
        return JSONResponse(status_code=http_status, content=asdict(to_payload(exc)))
