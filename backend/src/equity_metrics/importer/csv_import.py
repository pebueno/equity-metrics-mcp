"""Repeatable CSV import into the KPI schema.

The importer is idempotent: reference rows are resolved or created once, and
estimates are upserted on their source identity, so re-running the import over
the same file leaves the database unchanged.
"""

import csv
from collections.abc import Iterable
from dataclasses import dataclass, field
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from equity_metrics.db.models import Company, Estimate, KpiDefinition, Sector
from equity_metrics.domain.normalization import normalize_name
from equity_metrics.importer.rows import (
    REQUIRED_COLUMNS,
    RowError,
    RowValidationError,
    SourceRow,
    parse_row,
)

UPSERT_BATCH_SIZE = 500


@dataclass
class ImportReport:
    """Totals and rejections produced by a single import run."""

    rows_read: int = 0
    rows_imported: int = 0
    rows_rejected: int = 0
    sectors_created: int = 0
    companies_created: int = 0
    kpis_created: int = 0
    errors: list[RowError] = field(default_factory=list)

    def summary(self) -> str:
        """Return a one-line, log-friendly summary of the run."""
        return (
            f"read={self.rows_read} imported={self.rows_imported} "
            f"rejected={self.rows_rejected} sectors_created={self.sectors_created} "
            f"companies_created={self.companies_created} kpis_created={self.kpis_created}"
        )


class MissingColumnsError(Exception):
    """Raised when the CSV header does not match the dataset contract."""


def import_csv(path: Path, session: Session) -> ImportReport:
    """Import a CSV file. The caller owns the transaction and commits on success."""
    with path.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        missing = [column for column in REQUIRED_COLUMNS if column not in (reader.fieldnames or [])]
        if missing:
            raise MissingColumnsError(f"CSV is missing required columns: {', '.join(missing)}")
        return import_rows(reader, session)


def import_rows(raw_rows: Iterable[dict[str, str | None]], session: Session) -> ImportReport:
    """Validate and persist already-parsed CSV records."""
    report = ImportReport()
    resolver = _ReferenceResolver(session, report)
    pending: list[dict[str, object]] = []

    # Line 1 is the header, so data rows start at line 2.
    for line_number, raw in enumerate(raw_rows, start=2):
        report.rows_read += 1
        try:
            row = parse_row(raw)
            pending.append(resolver.to_estimate_values(row))
        except RowValidationError as exc:
            report.rows_rejected += 1
            report.errors.append(RowError(line_number, exc.field, exc.message))
            continue

        if len(pending) >= UPSERT_BATCH_SIZE:
            report.rows_imported += _upsert_estimates(session, pending)
            pending.clear()

    if pending:
        report.rows_imported += _upsert_estimates(session, pending)

    return report


def _upsert_estimates(session: Session, values: list[dict[str, object]]) -> int:
    """Insert or update estimates on their source identity and return the row count."""
    # PostgreSQL rejects a statement that touches the same conflict target twice,
    # so repeated source identities collapse here with the last occurrence winning.
    deduplicated: dict[tuple[object, ...], dict[str, object]] = {
        (row["company_id"], row["kpi_id"], row["period"], row["estimate_type"], row["as_of"]): row
        for row in values
    }
    statement = insert(Estimate).values(list(deduplicated.values()))
    statement = statement.on_conflict_do_update(
        index_elements=["company_id", "kpi_id", "period", "estimate_type", "as_of"],
        set_={
            "value": statement.excluded.value,
            "period_start": statement.excluded.period_start,
            "period_end": statement.excluded.period_end,
        },
    )
    session.execute(statement)
    return len(deduplicated)


class _ReferenceResolver:
    """Resolves sectors, companies, and KPIs to ids, creating them once per run."""

    def __init__(self, session: Session, report: ImportReport) -> None:
        self._session = session
        self._report = report
        self._sectors: dict[str, int] = {}
        self._companies: dict[str, int] = {}
        self._kpis: dict[str, int] = {}
        self._kpi_units: dict[str, str] = {}

    def to_estimate_values(self, row: SourceRow) -> dict[str, object]:
        """Map a validated row onto the columns of the estimates table."""
        return {
            "company_id": self._company_id(row),
            "kpi_id": self._kpi_id(row),
            "period": row.period,
            "period_start": row.period_start,
            "period_end": row.period_end,
            "estimate_type": row.estimate_type,
            "value": row.value,
            "as_of": row.as_of,
        }

    def _sector_id(self, name: str) -> int:
        key = normalize_name(name)
        if key not in self._sectors:
            sector = self._session.scalar(select(Sector).where(Sector.normalized_name == key))
            if sector is None:
                sector = Sector(name=name, normalized_name=key)
                self._session.add(sector)
                self._session.flush()
                self._report.sectors_created += 1
            self._sectors[key] = sector.id
        return self._sectors[key]

    def _company_id(self, row: SourceRow) -> int:
        if row.ticker not in self._companies:
            company = self._session.scalar(select(Company).where(Company.ticker == row.ticker))
            if company is None:
                company = Company(
                    sector_id=self._sector_id(row.sector),
                    name=row.company_name,
                    normalized_name=normalize_name(row.company_name),
                    ticker=row.ticker,
                )
                self._session.add(company)
                self._session.flush()
                self._report.companies_created += 1
            elif company.normalized_name != normalize_name(row.company_name):
                raise RowValidationError(
                    "company_name",
                    f"ticker {row.ticker} is already registered as {company.name!r}",
                )
            self._companies[row.ticker] = company.id
        return self._companies[row.ticker]

    def _kpi_id(self, row: SourceRow) -> int:
        key = normalize_name(row.kpi)
        if key not in self._kpis:
            kpi = self._session.scalar(
                select(KpiDefinition).where(KpiDefinition.normalized_name == key)
            )
            if kpi is None:
                kpi = KpiDefinition(
                    name=row.kpi,
                    normalized_name=key,
                    display_name=row.kpi,
                    unit=row.unit,
                )
                self._session.add(kpi)
                self._session.flush()
                self._report.kpis_created += 1
            self._kpis[key] = kpi.id
            self._kpi_units[key] = kpi.unit
        if self._kpi_units[key] != row.unit:
            raise RowValidationError(
                "unit",
                f"KPI {row.kpi!r} is reported in {self._kpi_units[key]!r}, not {row.unit!r}",
            )
        return self._kpis[key]
