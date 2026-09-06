"""Parameterized queries over the KPI schema.

This is the only module that builds SQL. Services compose these queries; they
never assemble statements themselves, so the API and the MCP tools share one
data-access path.
"""

from collections.abc import Sequence

from sqlalchemy import Row, func, or_, select
from sqlalchemy.orm import Session

from equity_metrics.db.models import Company, Estimate, KpiDefinition, Sector

# Search results are bounded so payloads stay small and predictable.
DEFAULT_SEARCH_LIMIT = 10
MAX_SEARCH_LIMIT = 50


def list_sectors(session: Session) -> Sequence[Row[tuple[str, int]]]:
    """Return every sector with its company count, ordered by name."""
    statement = (
        select(Sector.name, func.count(Company.id))
        .join(Company, Company.sector_id == Sector.id, isouter=True)
        .group_by(Sector.name)
        .order_by(Sector.name)
    )
    return session.execute(statement).all()


def find_company_by_ticker(session: Session, ticker: str) -> Company | None:
    """Look up a company by its canonical uppercase ticker."""
    return session.scalar(select(Company).where(Company.ticker == ticker))


def find_company_by_normalized_name(session: Session, normalized_name: str) -> Company | None:
    return session.scalar(select(Company).where(Company.normalized_name == normalized_name))


def search_companies(
    session: Session,
    *,
    query: str,
    sector: str | None = None,
    limit: int = DEFAULT_SEARCH_LIMIT,
) -> Sequence[Company]:
    """Return companies whose name, ticker, or sector contains the given text.

    Substring matching is used for search only; entity resolution requires an
    exact match. Ordering is by name so repeated calls are deterministic.
    """
    statement = select(Company).join(Sector, Company.sector_id == Sector.id)
    if query:
        pattern = f"%{_escape_like(query)}%"
        statement = statement.where(
            or_(
                Company.name.ilike(pattern, escape="\\"),
                Company.ticker.ilike(pattern, escape="\\"),
            )
        )
    if sector:
        statement = statement.where(Sector.name.ilike(f"%{_escape_like(sector)}%", escape="\\"))
    statement = statement.order_by(Company.name).limit(_bound(limit))
    return session.scalars(statement).all()


def find_kpi_by_normalized_name(session: Session, normalized_name: str) -> KpiDefinition | None:
    return session.scalar(
        select(KpiDefinition).where(KpiDefinition.normalized_name == normalized_name)
    )


def search_kpis(
    session: Session,
    *,
    query: str,
    company_id: int | None = None,
    limit: int = DEFAULT_SEARCH_LIMIT,
) -> Sequence[KpiDefinition]:
    """Return KPIs whose name contains the given text, optionally for one company."""
    statement = select(KpiDefinition)
    if query:
        statement = statement.where(
            KpiDefinition.name.ilike(f"%{_escape_like(query)}%", escape="\\")
        )
    if company_id is not None:
        statement = statement.where(
            KpiDefinition.id.in_(
                select(Estimate.kpi_id).where(Estimate.company_id == company_id).distinct()
            )
        )
    statement = statement.order_by(KpiDefinition.name).limit(_bound(limit))
    return session.scalars(statement).all()


def list_kpis_for_company(session: Session, company_id: int) -> Sequence[KpiDefinition]:
    """Return the KPIs a company actually reports, ordered by name."""
    statement = (
        select(KpiDefinition)
        .join(Estimate, Estimate.kpi_id == KpiDefinition.id)
        .where(Estimate.company_id == company_id)
        .distinct()
        .order_by(KpiDefinition.name)
    )
    return session.scalars(statement).all()


def list_historical_estimates(
    session: Session,
    *,
    company_id: int,
    kpi_id: int,
    periods: Sequence[str] | None = None,
) -> Sequence[Estimate]:
    """Return historical estimates in chronological order, optionally filtered."""
    statement = select(Estimate).where(
        Estimate.company_id == company_id,
        Estimate.kpi_id == kpi_id,
        Estimate.estimate_type == "historical",
    )
    if periods:
        statement = statement.where(Estimate.period.in_(list(periods)))
    return session.scalars(statement.order_by(Estimate.period)).all()


def find_latest_qtd_estimate(session: Session, *, company_id: int, kpi_id: int) -> Estimate | None:
    """Return the QTD snapshot with the greatest `as_of` date, not the greatest value."""
    statement = (
        select(Estimate)
        .where(
            Estimate.company_id == company_id,
            Estimate.kpi_id == kpi_id,
            Estimate.estimate_type == "qtd",
        )
        .order_by(Estimate.as_of.desc(), Estimate.id.desc())
        .limit(1)
    )
    return session.scalar(statement)


def list_all_kpis(session: Session) -> Sequence[KpiDefinition]:
    return session.scalars(select(KpiDefinition).order_by(KpiDefinition.name)).all()


def list_historical_for_company(session: Session, company_id: int) -> Sequence[Estimate]:
    statement = (
        select(Estimate)
        .where(Estimate.company_id == company_id, Estimate.estimate_type == "historical")
        .order_by(Estimate.kpi_id, Estimate.period)
    )
    return session.scalars(statement).all()


def list_latest_qtd_for_company(session: Session, company_id: int) -> Sequence[Estimate]:
    """The most recent QTD snapshot per KPI, chosen by greatest `as_of`.

    DISTINCT ON keeps this to a single indexed pass instead of one query per KPI.
    """
    statement = (
        select(Estimate)
        .where(Estimate.company_id == company_id, Estimate.estimate_type == "qtd")
        .distinct(Estimate.kpi_id)
        .order_by(Estimate.kpi_id, Estimate.as_of.desc(), Estimate.id.desc())
    )
    return session.scalars(statement).all()


def _bound(limit: int) -> int:
    """Clamp a caller-supplied limit into the supported range."""
    return max(1, min(limit, MAX_SEARCH_LIMIT))


def _escape_like(value: str) -> str:
    """Escape LIKE wildcards so user text matches literally."""
    return value.replace("\\", r"\\").replace("%", r"\%").replace("_", r"\_")
