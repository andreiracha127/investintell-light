"""per-user isolation: owner_sub/org_id on portfolios and screens

Revision ID: 0013
Revises: 0012
Create Date: 2026-06-18

Adds owner_sub (NOT NULL) and org_id (NULL) to the two root user-data tables
and swaps the global UNIQUE(name) for a per-owner UNIQUE(owner_sub, name).
Children (positions, screen_filters, rebalance_policies) are owned
transitively via their FK and get no column. Existing rows are test data with
no owner, so they are deleted before owner_sub becomes NOT NULL.
"""

import sqlalchemy as sa

from alembic import op

revision: str = "0013"
down_revision: str | None = "0012"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    # 1) Wipe pre-isolation test data (no owner to backfill). Children cascade:
    #    positions + rebalance_policies via portfolios; screen_filters via screens.
    op.execute("DELETE FROM positions")
    op.execute("DELETE FROM portfolios")
    op.execute("DELETE FROM screen_filters")
    op.execute("DELETE FROM screens")

    # 2) portfolios: add owner columns, swap unique(name) -> unique(owner_sub, name).
    op.add_column("portfolios", sa.Column("owner_sub", sa.String(), nullable=False))
    op.add_column("portfolios", sa.Column("org_id", sa.String(), nullable=True))
    op.drop_constraint("uq_portfolios_name", "portfolios", type_="unique")
    op.create_unique_constraint(
        "uq_portfolios_owner_sub", "portfolios", ["owner_sub", "name"]
    )

    # 3) screens: same treatment.
    op.add_column("screens", sa.Column("owner_sub", sa.String(), nullable=False))
    op.add_column("screens", sa.Column("org_id", sa.String(), nullable=True))
    op.drop_constraint("uq_screens_name", "screens", type_="unique")
    op.create_unique_constraint(
        "uq_screens_owner_sub", "screens", ["owner_sub", "name"]
    )


def downgrade() -> None:
    op.drop_constraint("uq_screens_owner_sub", "screens", type_="unique")
    op.create_unique_constraint("uq_screens_name", "screens", ["name"])
    op.drop_column("screens", "org_id")
    op.drop_column("screens", "owner_sub")

    op.drop_constraint("uq_portfolios_owner_sub", "portfolios", type_="unique")
    op.create_unique_constraint("uq_portfolios_name", "portfolios", ["name"])
    op.drop_column("portfolios", "org_id")
    op.drop_column("portfolios", "owner_sub")
