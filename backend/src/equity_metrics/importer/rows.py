"""Parsing and validation of source CSV rows.

This module is deliberately free of database access so row rules can be tested
without a running PostgreSQL instance.
"""

import datetime as dt
from collections.abc import Mapping
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation

from equity_metrics.db.models import ESTIMATE_TYPES
from equity_metrics.domain.normalization import (
    collapse_whitespace,
    is_valid_period,
    normalize_ticker,
)

REQUIRED_COLUMNS = (
    "company_name",
    "ticker",
    "sector",
    "kpi",
    "period_start",
    "period_end",
    "period",
    "estimate_type",
    "value",
    "unit",
    "as_of",
)


@dataclass(frozen=True, slots=True)
class SourceRow:
    """A validated CSV row, ready to be resolved against reference tables."""

    company_name: str
    ticker: str
    sector: str
    kpi: str
    period: str
    period_start: dt.date
    period_end: dt.date
    estimate_type: str
    value: Decimal
    unit: str
    as_of: dt.date | None


@dataclass(frozen=True, slots=True)
class RowError:
    """A rejected row, identified by its 1-based CSV line number."""

    line_number: int
    field: str
    message: str


class RowValidationError(Exception):
    """Raised when a CSV row violates the dataset contract."""

    def __init__(self, field: str, message: str) -> None:
        super().__init__(f"{field}: {message}")
        self.field = field
        self.message = message


def parse_row(raw: Mapping[str, str | None]) -> SourceRow:
    """Validate and normalize one CSV row, or raise `RowValidationError`."""
    company_name = _required_text(raw, "company_name")
    ticker = normalize_ticker(_required_text(raw, "ticker"))
    sector = _required_text(raw, "sector")
    kpi = _required_text(raw, "kpi")
    unit = _required_text(raw, "unit")

    period = collapse_whitespace(_required_text(raw, "period")).upper()
    if not is_valid_period(period):
        raise RowValidationError("period", f"expected YYYYQ[1-4], got {period!r}")

    estimate_type = _required_text(raw, "estimate_type").lower()
    if estimate_type not in ESTIMATE_TYPES:
        raise RowValidationError(
            "estimate_type", f"expected one of {ESTIMATE_TYPES}, got {estimate_type!r}"
        )

    period_start = _required_date(raw, "period_start")
    period_end = _required_date(raw, "period_end")
    if period_end < period_start:
        raise RowValidationError("period_end", "period_end precedes period_start")

    as_of = _optional_date(raw, "as_of")
    if estimate_type == "qtd" and as_of is None:
        raise RowValidationError("as_of", "as_of is required for qtd estimates")

    return SourceRow(
        company_name=collapse_whitespace(company_name),
        ticker=ticker,
        sector=collapse_whitespace(sector),
        kpi=collapse_whitespace(kpi),
        period=period,
        period_start=period_start,
        period_end=period_end,
        estimate_type=estimate_type,
        value=_decimal(raw, "value"),
        unit=collapse_whitespace(unit),
        as_of=as_of,
    )


def _required_text(raw: Mapping[str, str | None], field: str) -> str:
    value = collapse_whitespace(raw.get(field) or "")
    if not value:
        raise RowValidationError(field, "value is required")
    return value


def _decimal(raw: Mapping[str, str | None], field: str) -> Decimal:
    text = _required_text(raw, field)
    try:
        value = Decimal(text)
    except InvalidOperation as exc:
        raise RowValidationError(field, f"expected a decimal number, got {text!r}") from exc
    if not value.is_finite():
        raise RowValidationError(field, f"expected a finite number, got {text!r}")
    return value


def _required_date(raw: Mapping[str, str | None], field: str) -> dt.date:
    date = _optional_date(raw, field)
    if date is None:
        raise RowValidationError(field, "value is required")
    return date


def _optional_date(raw: Mapping[str, str | None], field: str) -> dt.date | None:
    text = collapse_whitespace(raw.get(field) or "")
    if not text:
        return None
    try:
        return dt.date.fromisoformat(text)
    except ValueError as exc:
        raise RowValidationError(field, f"expected an ISO-8601 date, got {text!r}") from exc
