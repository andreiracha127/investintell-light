"""portfolio owner isolation

Revision ID: 0016
Revises: 0015

Scope persisted portfolios by authenticated JWT subject. Existing single-tenant
portfolio rows are assigned to a one-time bootstrap owner when present.
"""

import os

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0016"
down_revision: str | None = "0015"
branch_labels: str | None = None
depends_on: str | None = None

_OWNER_ENV = "PORTFOLIO_BOOTSTRAP_OWNER_SUB"
_ORG_ENV = "PORTFOLIO_BOOTSTRAP_ORG_ID"


def upgrade() -> None:
    bind = op.get_bind()
    existing = bind.execute(sa.text("SELECT count(*) FROM portfolios")).scalar_one()
    owner_sub = os.getenv(_OWNER_ENV)
    org_id = os.getenv(_ORG_ENV)
    if existing and not owner_sub:
        raise RuntimeError(
            f"Set {_OWNER_ENV} to the JWT subject that should adopt the "
            "existing single-tenant portfolios before running migration 0016."
        )

    op.add_column("portfolios", sa.Column("owner_sub", sa.String(), nullable=True))
    op.add_column("portfolios", sa.Column("org_id", sa.String(), nullable=True))
    if existing:
        bind.execute(
            sa.text(
                "UPDATE portfolios SET owner_sub = :owner_sub, org_id = :org_id"
            ),
            {"owner_sub": owner_sub, "org_id": org_id},
        )
    op.alter_column("portfolios", "owner_sub", nullable=False)
    op.drop_constraint("uq_portfolios_name", "portfolios", type_="unique")
    op.create_unique_constraint(
        "uq_portfolios_owner_sub_name", "portfolios", ["owner_sub", "name"]
    )
    op.create_index(
        "ix_portfolios_owner_sub", "portfolios", ["owner_sub"], unique=False
    )


def downgrade() -> None:
    op.drop_index("ix_portfolios_owner_sub", table_name="portfolios")
    op.drop_constraint(
        "uq_portfolios_owner_sub_name", "portfolios", type_="unique"
    )
    op.create_unique_constraint("uq_portfolios_name", "portfolios", ["name"])
    op.drop_column("portfolios", "org_id")
    op.drop_column("portfolios", "owner_sub")
