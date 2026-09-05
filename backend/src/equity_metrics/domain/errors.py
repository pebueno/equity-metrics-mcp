"""Recoverable domain errors.

Every failure an investor or an LLM can correct is represented here with a
machine-readable code, the normalized query that was attempted, and a bounded
list of deterministic suggestions. The API and the MCP tools both surface these
without inventing their own vocabulary.
"""

from dataclasses import dataclass, field

MAX_SUGGESTIONS = 5


@dataclass(frozen=True, slots=True)
class Suggestion:
    """A concrete value the caller can retry with."""

    value: str
    label: str


class DomainError(Exception):
    """Base class for recoverable business errors."""

    code = "domain_error"

    def __init__(
        self,
        message: str,
        *,
        normalized_query: str,
        suggestions: list[Suggestion] | None = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.normalized_query = normalized_query
        self.suggestions = (suggestions or [])[:MAX_SUGGESTIONS]


class UnknownCompanyError(DomainError):
    """No company matched the query, exactly or by substring."""

    code = "unknown_company"


class AmbiguousCompanyError(DomainError):
    """The query did not match exactly but resembles known companies."""

    code = "ambiguous_company"


class UnknownKpiError(DomainError):
    """No KPI matched the query, exactly or by substring."""

    code = "unknown_kpi"


class AmbiguousKpiError(DomainError):
    """The query did not match exactly but resembles known KPIs."""

    code = "ambiguous_kpi"


class InvalidPeriodError(DomainError):
    """A requested fiscal period is not a `YYYYQ[1-4]` label."""

    code = "invalid_period"


class NoDataError(DomainError):
    """The company and KPI both resolved, but no estimate of that kind exists."""

    code = "no_data"


@dataclass(frozen=True, slots=True)
class ErrorPayload:
    """Serializable form of a domain error, shared by the API and MCP tools."""

    code: str
    message: str
    normalized_query: str
    suggestions: list[dict[str, str]] = field(default_factory=list)


def to_payload(error: DomainError) -> ErrorPayload:
    """Render a domain error as a stable, JSON-compatible payload."""
    return ErrorPayload(
        code=error.code,
        message=error.message,
        normalized_query=error.normalized_query,
        suggestions=[{"value": s.value, "label": s.label} for s in error.suggestions],
    )
