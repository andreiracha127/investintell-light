"""portfolio daily nav materialization

Revision ID: 0015
Revises: 0014

Persist the daily portfolio NAV index produced from the immutable transaction
ledger. Routes read this table; the worker is responsible for refreshing it
after EOD prices and ledger changes.
"""

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0015"
down_revision: str | None = "0014"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.create_table(
        "portfolio_nav_daily",
        sa.Column("portfolio_id", sa.Integer(), nullable=False),
        sa.Column("nav_date", sa.Date(), nullable=False),
        sa.Column("nav", sa.Float(), nullable=False),
        sa.Column("market_value", sa.Float(), nullable=False),
        sa.Column("cash", sa.Float(), nullable=False),
        sa.Column("total_value", sa.Float(), nullable=False),
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
            name=op.f("fk_portfolio_nav_daily_portfolio_id_portfolios"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint(
            "portfolio_id",
            "nav_date",
            name=op.f("pk_portfolio_nav_daily"),
        ),
        sa.CheckConstraint("nav > 0", name=op.f("ck_portfolio_nav_daily_nav_positive")),
    )
    op.create_index(
        "ix_portfolio_nav_daily_nav_date",
        "portfolio_nav_daily",
        ["nav_date"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_portfolio_nav_daily_nav_date", table_name="portfolio_nav_daily")
    op.drop_table("portfolio_nav_daily")
