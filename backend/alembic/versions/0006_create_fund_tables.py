"""create funds, fund_risk_latest, fund_nav, fund_holdings (F8.1)

Revision ID: 0006
Revises: 0005

Local read-only copies of mother-DB fund data, written ONLY by the fund sync
(scripts/sync_funds.py via app/sync/funds.py) — never in any request path:

- funds — identity + classification + fees per eligible instrument_id, with
  staleness fields (synced_at, source_calc_date, source_nav_max_date).
- fund_risk_latest — latest fund_risk_metrics snapshot per instrument
  (precomputed in the mother DB; every metric column is nullable).
- fund_nav — rolling daily NAV window (2y + 30d), composite PK
  (instrument_id, nav_date) doubles as the lookup index.
- fund_holdings — latest N-PORT report per series, ranked by pct_of_nav,
  with the top-50 truncation disclaimer flag.
"""

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0006"
down_revision: str | None = "0005"
branch_labels: str | None = None
depends_on: str | None = None

# All nullable numeric metric columns of fund_risk_latest, in model order
# (peer_strategy_label / peer_count / elite_flag are typed separately).
_RISK_NUMERIC_COLUMNS = (
    "return_1m",
    "return_3m",
    "return_1y",
    "return_3y_ann",
    "return_5y_ann",
    "volatility_1y",
    "max_drawdown_1y",
    "max_drawdown_3y",
    "sharpe_1y",
    "sharpe_3y",
    "sortino_1y",
    "calmar_ratio_3y",
    "alpha_1y",
    "beta_1y",
    "information_ratio_1y",
    "tracking_error_1y",
    "var_95_1m",
    "cvar_95_1m",
    "cvar_95_12m",
    "cvar_99_evt",
    "peer_sharpe_pctl",
    "peer_sortino_pctl",
    "peer_return_pctl",
    "peer_drawdown_pctl",
    "manager_score",
    "downside_capture_1y",
    "upside_capture_1y",
    "equity_correlation_252d",
)


def upgrade() -> None:
    # ------------------------------------------------------------------
    # funds
    # ------------------------------------------------------------------
    op.create_table(
        "funds",
        sa.Column("instrument_id", sa.Uuid(), nullable=False),
        sa.Column("series_id", sa.String(), nullable=False),
        sa.Column("ticker", sa.String(), nullable=True),
        sa.Column("isin", sa.String(), nullable=True),
        sa.Column("cusip", sa.String(), nullable=True),
        sa.Column("lei", sa.String(), nullable=True),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("fund_type", sa.String(), nullable=False),
        sa.Column("strategy_label", sa.String(), nullable=False),
        sa.Column("asset_class", sa.String(), nullable=True),
        sa.Column("is_index", sa.Boolean(), nullable=True),
        sa.Column("expense_ratio", sa.Numeric(), nullable=True),
        sa.Column("aum_usd", sa.Numeric(), nullable=True),
        sa.Column("primary_benchmark", sa.String(), nullable=True),
        sa.Column("inception_date", sa.Date(), nullable=True),
        sa.Column("domicile", sa.String(), nullable=True),
        sa.Column("currency", sa.String(), nullable=True),
        sa.Column("synced_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("source_calc_date", sa.Date(), nullable=False),
        sa.Column("source_nav_max_date", sa.Date(), nullable=False),
        sa.PrimaryKeyConstraint("instrument_id", name="pk_funds"),
    )
    op.create_index("ix_funds_series_id", "funds", ["series_id"], unique=False)
    op.create_index("ix_funds_fund_type", "funds", ["fund_type"], unique=False)
    op.create_index("ix_funds_strategy_label", "funds", ["strategy_label"], unique=False)
    op.create_index("ix_funds_asset_class", "funds", ["asset_class"], unique=False)

    # ------------------------------------------------------------------
    # fund_risk_latest
    # ------------------------------------------------------------------
    op.create_table(
        "fund_risk_latest",
        sa.Column("instrument_id", sa.Uuid(), nullable=False),
        sa.Column("calc_date", sa.Date(), nullable=False),
        *[sa.Column(name, sa.Numeric(), nullable=True) for name in _RISK_NUMERIC_COLUMNS],
        sa.Column("peer_strategy_label", sa.String(), nullable=True),
        sa.Column("peer_count", sa.Integer(), nullable=True),
        sa.Column("elite_flag", sa.Boolean(), nullable=True),
        sa.ForeignKeyConstraint(
            ["instrument_id"],
            ["funds.instrument_id"],
            name="fk_fund_risk_latest_instrument_id_funds",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("instrument_id", name="pk_fund_risk_latest"),
    )

    # ------------------------------------------------------------------
    # fund_nav
    # ------------------------------------------------------------------
    op.create_table(
        "fund_nav",
        sa.Column("instrument_id", sa.Uuid(), nullable=False),
        sa.Column("nav_date", sa.Date(), nullable=False),
        sa.Column("nav", sa.Numeric(), nullable=True),
        sa.Column("return_1d", sa.Numeric(), nullable=True),
        sa.Column("aum_usd", sa.Numeric(), nullable=True),
        sa.ForeignKeyConstraint(
            ["instrument_id"],
            ["funds.instrument_id"],
            name="fk_fund_nav_instrument_id_funds",
            ondelete="CASCADE",
        ),
        # Composite PK is also the (instrument_id, nav_date) lookup index.
        sa.PrimaryKeyConstraint("instrument_id", "nav_date", name="pk_fund_nav"),
    )

    # ------------------------------------------------------------------
    # fund_holdings
    # ------------------------------------------------------------------
    op.create_table(
        "fund_holdings",
        sa.Column("series_id", sa.String(), nullable=False),
        sa.Column("report_date", sa.Date(), nullable=False),
        sa.Column("rank", sa.Integer(), nullable=False),
        sa.Column("issuer_name", sa.String(), nullable=True),
        sa.Column("cusip", sa.String(), nullable=True),
        sa.Column("isin", sa.String(), nullable=True),
        sa.Column("asset_class", sa.String(), nullable=True),
        sa.Column("sector", sa.String(), nullable=True),
        sa.Column("market_value", sa.Numeric(), nullable=True),
        sa.Column("pct_of_nav", sa.Numeric(), nullable=True),
        sa.Column(
            "is_top50_truncated",
            sa.Boolean(),
            server_default="true",
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("series_id", "report_date", "rank", name="pk_fund_holdings"),
    )


def downgrade() -> None:
    op.drop_table("fund_holdings")
    op.drop_table("fund_nav")
    op.drop_table("fund_risk_latest")
    op.drop_index("ix_funds_asset_class", table_name="funds")
    op.drop_index("ix_funds_strategy_label", table_name="funds")
    op.drop_index("ix_funds_fund_type", table_name="funds")
    op.drop_index("ix_funds_series_id", table_name="funds")
    op.drop_table("funds")
