"""portfolio transaction ledger

Revision ID: 0013
Revises: 0012

Persist immutable buy/sell events for portfolios. The existing positions table
continues to represent the current snapshot; this ledger is the auditable input
for transaction-aware NAV reconstruction.
"""

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0013"
down_revision: str | None = "0012"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.create_table(
        "portfolio_transactions",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("portfolio_id", sa.Integer(), nullable=False),
        sa.Column("ticker", sa.String(), nullable=False),
        sa.Column("side", sa.String(), nullable=False),
        sa.Column("quantity", sa.Float(), nullable=False),
        sa.Column("price", sa.Float(), nullable=False),
        sa.Column("commission", sa.Numeric(), server_default="0", nullable=False),
        sa.Column("trade_date", sa.Date(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["portfolio_id"],
            ["portfolios.id"],
            name=op.f("fk_portfolio_transactions_portfolio_id_portfolios"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_portfolio_transactions")),
        sa.CheckConstraint(
            "side IN ('buy', 'sell')",
            name=op.f("ck_portfolio_transactions_side"),
        ),
        sa.CheckConstraint(
            "quantity > 0",
            name=op.f("ck_portfolio_transactions_quantity_positive"),
        ),
        sa.CheckConstraint(
            "price > 0",
            name=op.f("ck_portfolio_transactions_price_positive"),
        ),
        sa.CheckConstraint(
            "commission >= 0",
            name=op.f("ck_portfolio_transactions_commission_non_negative"),
        ),
    )
    op.create_index(
        "ix_portfolio_transactions_portfolio_id_trade_date",
        "portfolio_transactions",
        ["portfolio_id", "trade_date"],
        unique=False,
    )
    op.create_index(
        "ix_portfolio_transactions_ticker_trade_date",
        "portfolio_transactions",
        ["ticker", "trade_date"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_portfolio_transactions_ticker_trade_date",
        table_name="portfolio_transactions",
    )
    op.drop_index(
        "ix_portfolio_transactions_portfolio_id_trade_date",
        table_name="portfolio_transactions",
    )
    op.drop_table("portfolio_transactions")
