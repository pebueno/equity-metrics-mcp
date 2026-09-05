"""Shared KPI domain services.

The HTTP API and the MCP tools both call these functions, so validation,
entity resolution, and retrieval exist in exactly one place.
"""

from collections.abc import Sequence

from sqlalchemy.orm import Session

from equity_metrics.db import repositories
from equity_metrics.db.models import Company, KpiDefinition
from equity_metrics.domain.errors import (
    AmbiguousCompanyError,
    AmbiguousKpiError,
    InvalidPeriodError,
    NoDataError,
    Suggestion,
    UnknownCompanyError,
    UnknownKpiError,
)
from equity_metrics.domain.normalization import (
    collapse_whitespace,
    is_valid_period,
    normalize_name,
    normalize_ticker,
)
from equity_metrics.domain.schemas import (
    CompanyKpis,
    CompanySearchResult,
    CompanySummary,
    EstimatePoint,
    HistoricalEstimates,
    KpiSummary,
    QtdEstimate,
    SectorSummary,
)

# Guards the request payload; the sample dataset has 17 distinct periods.
MAX_REQUESTED_PERIODS = 40


def list_sectors(session: Session) -> list[SectorSummary]:
    """Return every sector with its company count."""
    return [
        SectorSummary(sector=name, company_count=count)
        for name, count in repositories.list_sectors(session)
    ]


def search_companies(
    session: Session,
    *,
    query: str,
    sector: str | None = None,
    limit: int = repositories.DEFAULT_SEARCH_LIMIT,
) -> CompanySearchResult:
    """Return bounded company candidates for a free-text query."""
    normalized = collapse_whitespace(query)
    companies = repositories.search_companies(
        session,
        query=normalized,
        sector=collapse_whitespace(sector) if sector else None,
        limit=limit,
    )
    return CompanySearchResult(
        query=normalized, companies=[_summarize(company) for company in companies]
    )


def resolve_company(session: Session, query: str) -> Company:
    """Resolve a ticker or company name to exactly one company.

    Exact ticker wins, then exact normalized company name. Anything else is a
    recoverable error carrying suggestions: a substring match is never promoted
    to a resolution, even when only one candidate exists, because that would
    silently choose on behalf of the caller.
    """
    normalized = collapse_whitespace(query)
    if not normalized:
        raise UnknownCompanyError(
            "A ticker or company name is required.", normalized_query=normalized
        )

    company = repositories.find_company_by_ticker(session, normalize_ticker(normalized))
    if company is not None:
        return company

    company = repositories.find_company_by_normalized_name(session, normalize_name(normalized))
    if company is not None:
        return company

    candidates = repositories.search_companies(session, query=normalized, limit=5)
    suggestions = [
        Suggestion(value=candidate.ticker, label=f"{candidate.name} ({candidate.ticker})")
        for candidate in candidates
    ]
    if suggestions:
        raise AmbiguousCompanyError(
            f"{normalized!r} did not match a ticker or company name exactly. "
            "Retry with one of the suggested tickers.",
            normalized_query=normalized,
            suggestions=suggestions,
        )
    raise UnknownCompanyError(
        f"No company matches {normalized!r}.",
        normalized_query=normalized,
    )


def resolve_kpi(session: Session, query: str, *, company: Company | None = None) -> KpiDefinition:
    """Resolve a KPI name exactly, or raise a recoverable error with suggestions."""
    normalized = collapse_whitespace(query)
    if not normalized:
        raise UnknownKpiError("A KPI name is required.", normalized_query=normalized)

    kpi = repositories.find_kpi_by_normalized_name(session, normalize_name(normalized))
    if kpi is not None:
        return kpi

    company_id = company.id if company is not None else None
    candidates = repositories.search_kpis(session, query=normalized, company_id=company_id, limit=5)
    suggestions = [
        Suggestion(value=candidate.name, label=candidate.name) for candidate in candidates
    ]
    if suggestions:
        raise AmbiguousKpiError(
            f"{normalized!r} did not match a KPI name exactly. Retry with one of the suggestions.",
            normalized_query=normalized,
            suggestions=suggestions,
        )
    raise UnknownKpiError(
        f"No KPI matches {normalized!r}.",
        normalized_query=normalized,
        suggestions=_all_kpi_suggestions(session, company_id),
    )


def list_company_kpis(session: Session, query: str) -> CompanyKpis:
    """Return the resolved company and the KPIs it reports."""
    company = resolve_company(session, query)
    kpis = repositories.list_kpis_for_company(session, company.id)
    return CompanyKpis(
        company=_summarize(company),
        kpis=[KpiSummary(kpi=kpi.name, unit=kpi.unit) for kpi in kpis],
    )


def get_historical_estimates(
    session: Session,
    *,
    company_query: str,
    kpi_query: str,
    periods: Sequence[str] | None = None,
) -> HistoricalEstimates:
    """Return historical estimates in chronological order for one company/KPI pair."""
    company = resolve_company(session, company_query)
    kpi = resolve_kpi(session, kpi_query, company=company)
    validated = _validate_periods(periods)

    estimates = repositories.list_historical_estimates(
        session, company_id=company.id, kpi_id=kpi.id, periods=validated
    )
    if not estimates:
        detail = f" in periods {', '.join(validated)}." if validated else "."
        raise NoDataError(
            f"No historical estimates for {kpi.name} at {company.ticker}{detail}",
            normalized_query=f"{company.ticker}/{kpi.name}",
        )

    return HistoricalEstimates(
        company=_summarize(company),
        kpi=kpi.name,
        unit=kpi.unit,
        estimates=[
            EstimatePoint(
                period=estimate.period,
                period_start=estimate.period_start,
                period_end=estimate.period_end,
                value=estimate.value,
                unit=kpi.unit,
            )
            for estimate in estimates
        ],
    )


def get_latest_qtd_estimate(session: Session, *, company_query: str, kpi_query: str) -> QtdEstimate:
    """Return the most recent QTD snapshot, chosen by the greatest `as_of` date."""
    company = resolve_company(session, company_query)
    kpi = resolve_kpi(session, kpi_query, company=company)

    estimate = repositories.find_latest_qtd_estimate(session, company_id=company.id, kpi_id=kpi.id)
    if estimate is None or estimate.as_of is None:
        raise NoDataError(
            f"No quarter-to-date snapshot for {kpi.name} at {company.ticker}.",
            normalized_query=f"{company.ticker}/{kpi.name}",
        )

    return QtdEstimate(
        company=_summarize(company),
        kpi=kpi.name,
        period=estimate.period,
        period_start=estimate.period_start,
        period_end=estimate.period_end,
        value=estimate.value,
        unit=kpi.unit,
        as_of=estimate.as_of,
    )


def _validate_periods(periods: Sequence[str] | None) -> list[str] | None:
    """Normalize and validate requested fiscal periods."""
    if not periods:
        return None
    normalized = [collapse_whitespace(period).upper() for period in periods]
    invalid = [period for period in normalized if not is_valid_period(period)]
    if invalid:
        raise InvalidPeriodError(
            f"Invalid fiscal period(s): {', '.join(invalid)}. "
            "Use the YYYYQ[1-4] form, for example 2024Q3.",
            normalized_query=", ".join(normalized),
        )
    if len(normalized) > MAX_REQUESTED_PERIODS:
        raise InvalidPeriodError(
            f"At most {MAX_REQUESTED_PERIODS} periods may be requested at once.",
            normalized_query=", ".join(normalized[:MAX_REQUESTED_PERIODS]),
        )
    return normalized


def _all_kpi_suggestions(session: Session, company_id: int | None) -> list[Suggestion]:
    """List available KPIs so a caller with an unknown name can still recover."""
    return [
        Suggestion(value=kpi.name, label=kpi.name)
        for kpi in repositories.search_kpis(session, query="", company_id=company_id, limit=5)
    ]


def _summarize(company: Company) -> CompanySummary:
    return CompanySummary(
        ticker=company.ticker, company_name=company.name, sector=company.sector.name
    )
