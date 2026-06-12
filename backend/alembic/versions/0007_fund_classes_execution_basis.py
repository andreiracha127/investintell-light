"""fund_classes catalog + executed-basis columns (F8.6b)

Revision ID: 0007
Revises: 0006

PROPOSTA vs carteira EXECUTADA:

- fund_classes — share-class catalog synced read-only from the mother DB's
  sec_fund_classes (latest filing per class_id). The mother DB prices ONE
  representative class per series, so any class ticker is priced with the
  SERIES NAV as a proxy (documented approximation, surfaced in the UI).
- positions.basis — 'reference' (spot/NAV used for analysis & sizing) or
  'executed' (real fill incl. commissions defines the cost basis);
  positions.commission / positions.trade_date carry the fill details.
- portfolios.origin — 'manual' | 'builder' provenance flag.
"""

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0007"
down_revision: str | None = "0006"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    # ------------------------------------------------------------------
    # fund_classes
    # ------------------------------------------------------------------
    op.create_table(
        "fund_classes",
        sa.Column("class_id", sa.String(), nullable=False),
        sa.Column("instrument_id", sa.Uuid(), nullable=False),
        sa.Column("series_id", sa.String(), nullable=True),
        sa.Column("class_name", sa.String(), nullable=True),
        sa.Column("ticker", sa.String(), nullable=False),
        sa.Column("expense_ratio", sa.Numeric(), nullable=True),
        sa.Column("source_period_end", sa.Date(), nullable=True),
        sa.Column("synced_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["instrument_id"],
            ["funds.instrument_id"],
            name="fk_fund_classes_instrument_id_funds",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("class_id", name="pk_fund_classes"),
    )
    op.create_index("ix_fund_classes_ticker", "fund_classes", ["ticker"], unique=False)
    op.create_index(
        "ix_fund_classes_instrument_id", "fund_classes", ["instrument_id"], unique=False
    )

    # ------------------------------------------------------------------
    # positions: basis / commission / trade_date
    # ------------------------------------------------------------------
    op.add_column(
        "positions",
        sa.Column(
            "basis", sa.String(), nullable=False, server_default="reference"
        ),
    )
    op.add_column("positions", sa.Column("commission", sa.Numeric(), nullable=True))
    op.add_column("positions", sa.Column("trade_date", sa.Date(), nullable=True))
    op.create_check_constraint(
        "basis",
        "positions",
        "basis IN ('reference', 'executed')",
    )
    op.create_check_constraint(
        "commission_non_negative",
        "positions",
        "commission IS NULL OR commission >= 0",
    )

    # ------------------------------------------------------------------
    # portfolios: origin
    # ------------------------------------------------------------------
    op.add_column(
        "portfolios",
        sa.Column("origin", sa.String(), nullable=False, server_default="manual"),
    )
    op.create_check_constraint(
        "origin",
        "portfolios",
        "origin IN ('manual', 'builder')",
    )


def downgrade() -> None:
    # Short names expand through the Base naming convention (ck_<table>_<name>).
    op.drop_constraint("origin", "portfolios", type_="check")
    op.drop_column("portfolios", "origin")
    op.drop_constraint("commission_non_negative", "positions", type_="check")
    op.drop_constraint("basis", "positions", type_="check")
    op.drop_column("positions", "trade_date")
    op.drop_column("positions", "commission")
    op.drop_column("positions", "basis")
    op.drop_index("ix_fund_classes_instrument_id", table_name="fund_classes")
    op.drop_index("ix_fund_classes_ticker", table_name="fund_classes")
    op.drop_table("fund_classes")
