"""create screener_metrics; index universe status; fundamentals cik NOT NULL

Revision ID: 0004
Revises: 0003
Create Date: 2026-06-11

- screener_metrics — one cross-sectional metrics row per universe constituent
  (FK to universe_constituents with ON DELETE CASCADE). Every metric column
  is nullable: NULL = "metric unavailable" (insufficient price history for
  the window, or a NULL/invalid fundamentals input). Written only by the
  batch metrics job (scripts/compute_screener_metrics.py).
- ix_universe_constituents_status — the backfill and metrics job both select
  WHERE status='active' (review follow-up).
- fundamentals_snapshot.cik SET NOT NULL — the sync always populates it (the
  snapshot is fetched BY cik); verified 0 NULL rows before this migration
  (review follow-up).
"""

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0004"
down_revision: str | None = "0003"
branch_labels: str | None = None
depends_on: str | None = None

# All nullable double-precision metric columns, in model order.
_FLOAT_METRIC_COLUMNS = (
    # trailing returns
    "ret_1w",
    "ret_1m",
    "ret_3m",
    "ret_6m",
    "ret_1y",
    "ret_ytd",
    "ret_mtd",
    # annualized volatility
    "vol_1m",
    "vol_3m",
    "vol_6m",
    "vol_1y",
    # beta vs SPY
    "beta_3m_spy",
    "beta_6m_spy",
    "beta_1y_spy",
    "beta_2y_spy",
    # 1y correlation vs ETF proxies
    "corr_spy",
    "corr_gld",
    "corr_agg",
    "corr_tlt",
    "corr_uso",
    # SMA distance
    "pct_above_sma20",
    "pct_above_sma50",
    "pct_above_sma200",
    # levels
    "price_close",
    "avg_volume_1m",
    # fundamentals-derived
    "market_cap",
    "pe_ratio",
    "roe",
    "roa",
    "gross_margin",
    "de_ratio",
    "investment_growth",
    "profitability_gross",
)


def upgrade() -> None:
    # ------------------------------------------------------------------
    # screener_metrics
    # ------------------------------------------------------------------
    op.create_table(
        "screener_metrics",
        sa.Column("ticker", sa.String(), nullable=False),
        sa.Column("computed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("as_of", sa.Date(), nullable=False),
        *[
            sa.Column(name, sa.Double(), nullable=True)
            for name in _FLOAT_METRIC_COLUMNS
        ],
        sa.Column("fundamentals_period_end", sa.Date(), nullable=True),
        sa.ForeignKeyConstraint(
            ["ticker"],
            ["universe_constituents.ticker"],
            name="fk_screener_metrics_ticker_universe_constituents",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("ticker", name="pk_screener_metrics"),
    )

    # ------------------------------------------------------------------
    # Review follow-ups
    # ------------------------------------------------------------------
    op.create_index(
        "ix_universe_constituents_status",
        "universe_constituents",
        ["status"],
        unique=False,
    )
    op.alter_column(
        "fundamentals_snapshot",
        "cik",
        existing_type=sa.BigInteger(),
        nullable=False,
    )


def downgrade() -> None:
    op.alter_column(
        "fundamentals_snapshot",
        "cik",
        existing_type=sa.BigInteger(),
        nullable=True,
    )
    op.drop_index(
        "ix_universe_constituents_status", table_name="universe_constituents"
    )
    op.drop_table("screener_metrics")
