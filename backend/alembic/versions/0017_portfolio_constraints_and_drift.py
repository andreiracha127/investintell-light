"""portfolio constraints and drift status tables

Revision ID: 0017
Revises: 0016

Create the persistence tables used by the portfolio construction constraint
and drift-monitor services.
"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0017"
down_revision: str | None = "0016"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.create_table(
        "portfolio_constraint_set",
        sa.Column("portfolio_id", sa.Integer(), nullable=False),
        sa.Column("cap", sa.Float(), nullable=True),
        sa.Column("min_weight", sa.Float(), nullable=True),
        sa.Column("overlap_cap", sa.Float(), nullable=True),
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
            name=op.f("fk_portfolio_constraint_set_portfolio_id_portfolios"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint(
            "portfolio_id",
            name=op.f("pk_portfolio_constraint_set"),
        ),
    )

    op.create_table(
        "portfolio_class_limits",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("portfolio_id", sa.Integer(), nullable=False),
        sa.Column("asset_class", sa.String(), nullable=False),
        sa.Column("min_weight", sa.Float(), nullable=True),
        sa.Column("max_weight", sa.Float(), nullable=True),
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
            name=op.f("fk_portfolio_class_limits_portfolio_id_portfolios"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_portfolio_class_limits")),
        sa.UniqueConstraint(
            "portfolio_id",
            "asset_class",
            name="uq_portfolio_class_limits_portfolio_id_asset_class",
        ),
        sa.CheckConstraint(
            "asset_class IN "
            "('equity', 'fixed_income', 'cash', 'alternatives', 'multi_asset')",
            name=op.f("ck_portfolio_class_limits_asset_class"),
        ),
    )
    op.create_index(
        "ix_portfolio_class_limits_portfolio_id",
        "portfolio_class_limits",
        ["portfolio_id"],
        unique=False,
    )

    op.create_table(
        "portfolio_drift_status",
        sa.Column("portfolio_id", sa.Integer(), nullable=False),
        sa.Column("evaluated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("worst_status", sa.Text(), nullable=False),
        sa.Column("breaches", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
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
            name=op.f("fk_portfolio_drift_status_portfolio_id_portfolios"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("portfolio_id", name=op.f("pk_portfolio_drift_status")),
        sa.CheckConstraint(
            "worst_status IN ('ok', 'maintenance', 'urgent')",
            name=op.f("ck_portfolio_drift_status_worst_status"),
        ),
    )


def downgrade() -> None:
    op.drop_table("portfolio_drift_status")
    op.drop_index(
        "ix_portfolio_class_limits_portfolio_id",
        table_name="portfolio_class_limits",
    )
    op.drop_table("portfolio_class_limits")
    op.drop_table("portfolio_constraint_set")
