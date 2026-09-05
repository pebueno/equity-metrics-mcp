"""create kpi schema

Revision ID: 6784cc621099
Revises:
Create Date: 2026-09-05 13:08:22.866795

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "6784cc621099"
down_revision: str | Sequence[str] | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Create reference, estimate, and audit tables."""
    op.create_table(
        "kpi_definitions",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=160), nullable=False),
        sa.Column("normalized_name", sa.String(length=160), nullable=False),
        sa.Column("display_name", sa.String(length=160), nullable=False),
        sa.Column("unit", sa.String(length=32), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("normalized_name", name="uq_kpi_definitions_normalized"),
    )
    op.create_table(
        "mcp_tool_calls",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("correlation_id", sa.String(length=64), nullable=False),
        sa.Column("tool_name", sa.String(length=64), nullable=False),
        sa.Column("sanitized_arguments", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("outcome", sa.String(length=16), nullable=False),
        sa.Column("error_code", sa.String(length=64), nullable=True),
        sa.Column("duration_ms", sa.Integer(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_mcp_tool_calls_created_at", "mcp_tool_calls", ["created_at"], unique=False)
    op.create_table(
        "sectors",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("normalized_name", sa.String(length=120), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("normalized_name", name="uq_sectors_normalized_name"),
    )
    op.create_table(
        "companies",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("sector_id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("normalized_name", sa.String(length=200), nullable=False),
        sa.Column("ticker", sa.String(length=16), nullable=False),
        sa.ForeignKeyConstraint(
            ["sector_id"],
            ["sectors.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("normalized_name", name="uq_companies_normalized_name"),
        sa.UniqueConstraint("ticker", name="uq_companies_ticker"),
    )
    op.create_table(
        "estimates",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("company_id", sa.Integer(), nullable=False),
        sa.Column("kpi_id", sa.Integer(), nullable=False),
        sa.Column("period", sa.String(length=6), nullable=False),
        sa.Column("period_start", sa.Date(), nullable=False),
        sa.Column("period_end", sa.Date(), nullable=False),
        sa.Column("estimate_type", sa.String(length=16), nullable=False),
        sa.Column("value", sa.Numeric(precision=20, scale=6), nullable=False),
        sa.Column("as_of", sa.Date(), nullable=True),
        sa.CheckConstraint(
            "estimate_type <> 'qtd' OR as_of IS NOT NULL", name="ck_estimates_qtd_requires_as_of"
        ),
        sa.CheckConstraint(
            "estimate_type IN ('historical', 'qtd')", name="ck_estimates_estimate_type"
        ),
        sa.CheckConstraint("period ~ '^[0-9]{4}Q[1-4]$'", name="ck_estimates_period_format"),
        sa.ForeignKeyConstraint(
            ["company_id"],
            ["companies.id"],
        ),
        sa.ForeignKeyConstraint(
            ["kpi_id"],
            ["kpi_definitions.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_estimates_company_kpi_as_of",
        "estimates",
        ["company_id", "kpi_id", "as_of"],
        unique=False,
        postgresql_where="estimate_type = 'qtd'",
    )
    op.create_index(
        "ix_estimates_company_kpi_period",
        "estimates",
        ["company_id", "kpi_id", "period"],
        unique=False,
    )
    op.create_index(
        "uq_estimates_source_identity",
        "estimates",
        ["company_id", "kpi_id", "period", "estimate_type", "as_of"],
        unique=True,
        postgresql_nulls_not_distinct=True,
    )


def downgrade() -> None:
    """Drop every table created by this revision."""
    op.drop_index(
        "uq_estimates_source_identity", table_name="estimates", postgresql_nulls_not_distinct=True
    )
    op.drop_index("ix_estimates_company_kpi_period", table_name="estimates")
    op.drop_index(
        "ix_estimates_company_kpi_as_of",
        table_name="estimates",
        postgresql_where="estimate_type = 'qtd'",
    )
    op.drop_table("estimates")
    op.drop_table("companies")
    op.drop_table("sectors")
    op.drop_index("ix_mcp_tool_calls_created_at", table_name="mcp_tool_calls")
    op.drop_table("mcp_tool_calls")
    op.drop_table("kpi_definitions")
