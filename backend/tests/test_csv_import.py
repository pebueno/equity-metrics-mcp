"""Importer behavior against PostgreSQL: idempotency, rejection, and QTD ordering."""

import datetime as dt
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from equity_metrics.db.models import Company, Estimate, KpiDefinition, Sector
from equity_metrics.importer.csv_import import import_csv, import_rows

from .conftest import SAMPLE_CSV

BASE_ROW = {
    "company_name": "Acme E-commerce",
    "ticker": "ACME",
    "sector": "E-commerce",
    "kpi": "ASP ($)",
    "period_start": "2022-01-01",
    "period_end": "2022-03-31",
    "period": "2022Q1",
    "estimate_type": "historical",
    "value": "128.67",
    "unit": "$",
    "as_of": "",
}


def _row(**overrides: str) -> dict[str, str | None]:
    return {**BASE_ROW, **overrides}


def _counts(session: Session) -> tuple[int, int, int, int]:
    return (
        session.scalar(select(func.count()).select_from(Sector)) or 0,
        session.scalar(select(func.count()).select_from(Company)) or 0,
        session.scalar(select(func.count()).select_from(KpiDefinition)) or 0,
        session.scalar(select(func.count()).select_from(Estimate)) or 0,
    )


def test_imports_the_sample_dataset(session: Session) -> None:
    report = import_csv(SAMPLE_CSV, session)
    session.commit()

    assert report.rows_read == 2000
    assert report.rows_rejected == 0
    assert report.rows_imported == 2000
    assert _counts(session) == (18, 20, 5, 2000)


def test_importing_twice_leaves_the_same_state(session: Session) -> None:
    import_csv(SAMPLE_CSV, session)
    session.commit()
    first = _counts(session)

    second_report = import_csv(SAMPLE_CSV, session)
    session.commit()

    assert _counts(session) == first
    assert second_report.sectors_created == 0
    assert second_report.companies_created == 0
    assert second_report.kpis_created == 0


def test_reimport_updates_a_changed_value_in_place(session: Session) -> None:
    import_rows([_row()], session)
    session.commit()

    import_rows([_row(value="130.00")], session)
    session.commit()

    estimates = session.scalars(select(Estimate)).all()
    assert len(estimates) == 1
    assert estimates[0].value == Decimal("130.000000")


def test_rejects_malformed_rows_and_keeps_importing(session: Session) -> None:
    report = import_rows(
        [_row(), _row(period="2022Q9", period_start="2022-04-01"), _row(period="2022Q2")],
        session,
    )
    session.commit()

    assert report.rows_read == 3
    assert report.rows_imported == 2
    assert report.rows_rejected == 1
    assert [(error.line_number, error.field) for error in report.errors] == [(3, "period")]


def test_rejects_a_unit_that_contradicts_the_kpi_definition(session: Session) -> None:
    report = import_rows([_row(), _row(period="2022Q2", unit="EUR")], session)
    session.commit()

    assert report.rows_rejected == 1
    assert report.errors[0].field == "unit"


def test_keeps_every_qtd_snapshot_and_orders_by_as_of(session: Session) -> None:
    snapshots = ["2026-02-28", "2026-01-31", "2026-02-15"]
    import_rows(
        [
            _row(
                period="2026Q1",
                period_start="2026-01-01",
                period_end="2026-03-31",
                estimate_type="qtd",
                value=f"16{index}.00",
                as_of=as_of,
            )
            for index, as_of in enumerate(snapshots)
        ],
        session,
    )
    session.commit()

    latest = session.scalars(
        select(Estimate).where(Estimate.estimate_type == "qtd").order_by(Estimate.as_of.desc())
    ).all()

    assert len(latest) == 3
    # Latest QTD is the greatest as_of date, not the greatest value.
    assert latest[0].as_of == dt.date(2026, 2, 28)
    assert latest[0].value == Decimal("160.000000")


def test_duplicate_source_identity_within_one_file_collapses(session: Session) -> None:
    report = import_rows([_row(), _row(value="999.00")], session)
    session.commit()

    assert report.rows_imported == 1
    assert session.scalars(select(Estimate)).one().value == Decimal("999.000000")
