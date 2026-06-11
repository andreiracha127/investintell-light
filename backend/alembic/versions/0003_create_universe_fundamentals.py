"""create universe_constituents and fundamentals_snapshot tables

Revision ID: 0003
Revises: 0002
Create Date: 2026-06-11

Creates two plain (non-hypertable) tables for the screener universe (F6):
  - universe_constituents — US equities derived from the SEC company_tickers
    crosswalk joined by CIK against the mother DB's active fundamentals set
  - fundamentals_snapshot — latest RAW fundamentals row per ticker (one row
    per constituent; FK to universe_constituents with ON DELETE CASCADE)

Both tables are written only by the batch sync/backfill scripts.
"""

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    # ------------------------------------------------------------------
    # universe_constituents
    # ------------------------------------------------------------------
    op.create_table(
        "universe_constituents",
        sa.Column("ticker", sa.String(), nullable=False),
        sa.Column("cik", sa.BigInteger(), nullable=False),
        sa.Column("name", sa.String(), nullable=True),
        sa.Column("status", sa.String(), server_default="active", nullable=False),
        sa.Column("source", sa.String(), nullable=False),
        sa.Column("synced_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("ticker", name="pk_universe_constituents"),
    )
    op.create_index(
        "ix_universe_constituents_cik",
        "universe_constituents",
        ["cik"],
        unique=False,
    )

    # ------------------------------------------------------------------
    # fundamentals_snapshot
    # ------------------------------------------------------------------
    op.create_table(
        "fundamentals_snapshot",
        sa.Column("ticker", sa.String(), nullable=False),
        sa.Column("cik", sa.BigInteger(), nullable=True),
        sa.Column("period_end", sa.Date(), nullable=False),
        sa.Column("book_equity", sa.Double(), nullable=True),
        sa.Column("total_assets", sa.Double(), nullable=True),
        sa.Column("net_income_ttm", sa.Double(), nullable=True),
        sa.Column("revenue", sa.Double(), nullable=True),
        sa.Column("gross_profit", sa.Double(), nullable=True),
        sa.Column("shares_outstanding", sa.Double(), nullable=True),
        sa.Column("quality_roa", sa.Double(), nullable=True),
        sa.Column("investment_growth", sa.Double(), nullable=True),
        sa.Column("profitability_gross", sa.Double(), nullable=True),
        sa.Column("source_filing_date", sa.Date(), nullable=True),
        sa.Column("synced_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["ticker"],
            ["universe_constituents.ticker"],
            name="fk_fundamentals_snapshot_ticker_universe_constituents",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("ticker", name="pk_fundamentals_snapshot"),
    )


def downgrade() -> None:
    # Drop in reverse dependency order.
    op.drop_table("fundamentals_snapshot")
    op.drop_index(
        "ix_universe_constituents_cik", table_name="universe_constituents"
    )
    op.drop_table("universe_constituents")
