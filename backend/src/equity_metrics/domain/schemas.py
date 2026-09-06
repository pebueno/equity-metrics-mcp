"""Typed response models shared by the HTTP API and the MCP tools.

Field names are stable and every numeric estimate travels with its unit.
Decimals are serialized as JSON strings so exact precision survives the wire.
"""

import datetime as dt
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, field_serializer


def format_decimal(value: Decimal) -> str:
    """Render a stored value without the padding zeros NUMERIC(20, 6) adds."""
    trimmed = value.normalize()
    if trimmed == trimmed.to_integral_value():
        trimmed = trimmed.quantize(Decimal(1))
    return format(trimmed, "f")


class _Model(BaseModel):
    model_config = ConfigDict(frozen=True)


class SectorSummary(_Model):
    """A sector and how many companies it contains."""

    sector: str
    company_count: int


class CompanySummary(_Model):
    """Canonical identity of a company."""

    ticker: str
    company_name: str
    sector: str


class CompanySearchResult(_Model):
    """Bounded, deterministic company candidates for a search query."""

    query: str
    companies: list[CompanySummary]


class KpiSummary(_Model):
    """A KPI available for a company, with the unit its values use."""

    kpi: str
    unit: str


class CompanyKpis(_Model):
    """The KPIs a resolved company reports."""

    company: CompanySummary
    kpis: list[KpiSummary]


class EstimatePoint(_Model):
    """One historical estimate for a fiscal period."""

    period: str
    period_start: dt.date
    period_end: dt.date
    value: Decimal
    unit: str

    @field_serializer("value")
    def _serialize_value(self, value: Decimal) -> str:
        return format_decimal(value)


class HistoricalEstimates(_Model):
    """Historical estimates for a company/KPI pair in chronological order."""

    company: CompanySummary
    kpi: str
    unit: str
    estimates: list[EstimatePoint]


class QtdPoint(_Model):
    """A quarter-to-date snapshot without the company repeated on every row."""

    period: str
    period_start: dt.date
    period_end: dt.date
    value: Decimal
    unit: str
    as_of: dt.date

    @field_serializer("value")
    def _serialize_value(self, value: Decimal) -> str:
        return format_decimal(value)


class KpiOverview(_Model):
    """One KPI for a company: its full history and its latest QTD snapshot."""

    kpi: str
    unit: str
    history: list[EstimatePoint]
    qtd: QtdPoint | None


class CompanyOverview(_Model):
    """Everything published for one company, in a single response."""

    company: CompanySummary
    kpis: list[KpiOverview]


class QtdEstimate(_Model):
    """The most recent quarter-to-date snapshot for a company/KPI pair."""

    company: CompanySummary
    kpi: str
    period: str
    period_start: dt.date
    period_end: dt.date
    value: Decimal
    unit: str
    as_of: dt.date

    @field_serializer("value")
    def _serialize_value(self, value: Decimal) -> str:
        return format_decimal(value)
