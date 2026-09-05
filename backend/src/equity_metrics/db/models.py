"""ORM models for KPI reference data, estimates, and the MCP audit trail."""

import datetime as dt
from decimal import Decimal

from sqlalchemy import (
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from equity_metrics.db.base import Base

ESTIMATE_TYPES = ("historical", "qtd")


class Sector(Base):
    """Industry classification for a company."""

    __tablename__ = "sectors"
    __table_args__ = (UniqueConstraint("normalized_name", name="uq_sectors_normalized_name"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    normalized_name: Mapped[str] = mapped_column(String(120), nullable=False)

    companies: Mapped[list["Company"]] = relationship(back_populates="sector")


class Company(Base):
    """A public company identified canonically by its uppercase ticker."""

    __tablename__ = "companies"
    __table_args__ = (
        UniqueConstraint("ticker", name="uq_companies_ticker"),
        UniqueConstraint("normalized_name", name="uq_companies_normalized_name"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    sector_id: Mapped[int] = mapped_column(ForeignKey("sectors.id"), nullable=False)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    normalized_name: Mapped[str] = mapped_column(String(200), nullable=False)
    ticker: Mapped[str] = mapped_column(String(16), nullable=False)

    sector: Mapped[Sector] = relationship(back_populates="companies")


class KpiDefinition(Base):
    """A KPI and the unit its values are reported in."""

    __tablename__ = "kpi_definitions"
    __table_args__ = (UniqueConstraint("normalized_name", name="uq_kpi_definitions_normalized"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    normalized_name: Mapped[str] = mapped_column(String(160), nullable=False)
    display_name: Mapped[str] = mapped_column(String(160), nullable=False)
    unit: Mapped[str] = mapped_column(String(32), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)


class Estimate(Base):
    """One historical or QTD estimate for a company/KPI/fiscal period."""

    __tablename__ = "estimates"
    __table_args__ = (
        CheckConstraint(
            "estimate_type IN ('historical', 'qtd')", name="ck_estimates_estimate_type"
        ),
        CheckConstraint("period ~ '^[0-9]{4}Q[1-4]$'", name="ck_estimates_period_format"),
        # QTD rows are only meaningful with a snapshot date; historical rows may omit it.
        CheckConstraint(
            "estimate_type <> 'qtd' OR as_of IS NOT NULL", name="ck_estimates_qtd_requires_as_of"
        ),
        # Source row identity. NULLS NOT DISTINCT (PostgreSQL 15+) keeps historical
        # rows, whose as_of is NULL, from being re-inserted on every import.
        Index(
            "uq_estimates_source_identity",
            "company_id",
            "kpi_id",
            "period",
            "estimate_type",
            "as_of",
            unique=True,
            postgresql_nulls_not_distinct=True,
        ),
        Index("ix_estimates_company_kpi_period", "company_id", "kpi_id", "period"),
        Index(
            "ix_estimates_company_kpi_as_of",
            "company_id",
            "kpi_id",
            "as_of",
            postgresql_where="estimate_type = 'qtd'",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("companies.id"), nullable=False)
    kpi_id: Mapped[int] = mapped_column(ForeignKey("kpi_definitions.id"), nullable=False)
    period: Mapped[str] = mapped_column(String(6), nullable=False)
    period_start: Mapped[dt.date] = mapped_column(Date, nullable=False)
    period_end: Mapped[dt.date] = mapped_column(Date, nullable=False)
    estimate_type: Mapped[str] = mapped_column(String(16), nullable=False)
    value: Mapped[Decimal] = mapped_column(Numeric(20, 6), nullable=False)
    as_of: Mapped[dt.date | None] = mapped_column(Date, nullable=True)

    company: Mapped[Company] = relationship()
    kpi: Mapped[KpiDefinition] = relationship()


class McpToolCall(Base):
    """Audit record written for every MCP tool invocation, success or failure."""

    __tablename__ = "mcp_tool_calls"
    __table_args__ = (Index("ix_mcp_tool_calls_created_at", "created_at"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    correlation_id: Mapped[str] = mapped_column(String(64), nullable=False)
    tool_name: Mapped[str] = mapped_column(String(64), nullable=False)
    sanitized_arguments: Mapped[dict[str, object]] = mapped_column(JSONB, nullable=False)
    outcome: Mapped[str] = mapped_column(String(16), nullable=False)
    error_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    duration_ms: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
