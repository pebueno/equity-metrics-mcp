"""HTTP endpoints over the shared KPI services.

Routes stay thin on purpose: they bind and bound request input, delegate to
`kpi_service`, and let the domain error handler shape failures. No validation
or SQL is duplicated here.
"""

from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from equity_metrics.api.deps import get_session
from equity_metrics.db.repositories import DEFAULT_SEARCH_LIMIT, MAX_SEARCH_LIMIT
from equity_metrics.domain.schemas import (
    CompanyKpis,
    CompanyOverview,
    CompanySearchResult,
    HistoricalEstimates,
    KpiSummary,
    QtdEstimate,
    SectorSummary,
)
from equity_metrics.services import kpi_service

router = APIRouter(prefix="/api")

SessionDep = Annotated[Session, Depends(get_session)]


@router.get("/sectors", response_model=list[SectorSummary])
def get_sectors(session: SessionDep) -> list[SectorSummary]:
    """List every sector with its company count."""
    return kpi_service.list_sectors(session)


@router.get("/companies", response_model=CompanySearchResult)
def get_companies(
    session: SessionDep,
    query: Annotated[str, Query(max_length=120)] = "",
    sector: Annotated[str | None, Query(max_length=120)] = None,
    limit: Annotated[int, Query(ge=1, le=MAX_SEARCH_LIMIT)] = DEFAULT_SEARCH_LIMIT,
) -> CompanySearchResult:
    """Search companies by name, ticker, or sector."""
    return kpi_service.search_companies(session, query=query, sector=sector, limit=limit)


@router.get("/kpis", response_model=list[KpiSummary])
def get_kpis(session: SessionDep) -> list[KpiSummary]:
    """List every KPI in the dataset with its unit."""
    return kpi_service.list_kpis(session)


@router.get("/companies/{company}/overview", response_model=CompanyOverview)
def get_company_overview(company: str, session: SessionDep) -> CompanyOverview:
    """Return every KPI for a company with its history and latest QTD snapshot."""
    return kpi_service.get_company_overview(session, company)


@router.get("/companies/{company}/kpis", response_model=CompanyKpis)
def get_company_kpis(company: str, session: SessionDep) -> CompanyKpis:
    """Resolve a company and list the KPIs it reports."""
    return kpi_service.list_company_kpis(session, company)


@router.get("/companies/{company}/kpis/{kpi}/estimates", response_model=HistoricalEstimates)
def get_estimates(
    company: str,
    kpi: str,
    session: SessionDep,
    periods: Annotated[list[str] | None, Query()] = None,
) -> HistoricalEstimates:
    """Return historical estimates in chronological order."""
    return kpi_service.get_historical_estimates(
        session, company_query=company, kpi_query=kpi, periods=periods
    )


@router.get("/companies/{company}/kpis/{kpi}/qtd", response_model=QtdEstimate)
def get_qtd(company: str, kpi: str, session: SessionDep) -> QtdEstimate:
    """Return the most recent quarter-to-date snapshot."""
    return kpi_service.get_latest_qtd_estimate(session, company_query=company, kpi_query=kpi)
