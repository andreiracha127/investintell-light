"""add optimize_jobs table and portfolio owner isolation

Revision ID: 0016
Revises: 0015

Spec divergence: the DB-First spec says to "reuse" optimize_jobs, but the table
did not exist in this branch. It is created here. The upgrade is guarded by an
existence check so it is idempotent if the table already exists in production
with a compatible shape.

This revision also folds in the production-applied portfolio owner isolation
step. A previous branch used the same revision id (0016) for owner isolation
only; keeping both changes here preserves a single Alembic chain for fresh
databases while matching the already-migrated production schema.
"""

import os

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0016"
down_revision: str | None = "0015"
branch_labels: str | None = None
depends_on: str | None = None

_OWNER_ENV = "PORTFOLIO_BOOTSTRAP_OWNER_SUB"
_ORG_ENV = "PORTFOLIO_BOOTSTRAP_ORG_ID"


def _ensure_optimize_jobs(insp: sa.Inspector) -> None:
    if "optimize_jobs" in insp.get_table_names():
        return  # tabela já existe em prod - não recriar (divergência da spec)
    op.create_table(
        "optimize_jobs",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("portfolio_id", sa.Integer(), nullable=True),
        sa.Column("kind", sa.String(), nullable=False),
        sa.Column("params_hash", sa.String(), nullable=False),
        sa.Column("status", sa.String(), nullable=False, server_default="pending"),
        sa.Column("result", postgresql.JSONB(), nullable=True),
        sa.Column("error", sa.String(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.CheckConstraint(
            "status IN ('pending', 'running', 'succeeded', 'failed')",
            name="ck_optimize_jobs_status",
        ),
    )
    op.create_index(
        "ix_optimize_jobs_kind_params_hash",
        "optimize_jobs",
        ["kind", "params_hash"],
    )


def _ensure_portfolio_owner_isolation(bind: sa.Connection, insp: sa.Inspector) -> None:
    if "portfolios" not in insp.get_table_names():
        return

    columns = {column["name"] for column in insp.get_columns("portfolios")}
    existing_rows = bind.execute(sa.text("SELECT count(*) FROM portfolios")).scalar_one()
    owner_sub = os.getenv(_OWNER_ENV)
    org_id = os.getenv(_ORG_ENV)
    needs_owner_backfill = (
        "owner_sub" not in columns
        or bind.execute(
            sa.text("SELECT EXISTS (SELECT 1 FROM portfolios WHERE owner_sub IS NULL)")
        ).scalar_one()
    )
    if existing_rows and needs_owner_backfill and not owner_sub:
        raise RuntimeError(
            f"Set {_OWNER_ENV} to the JWT subject that should adopt the "
            "existing single-tenant portfolios before running migration 0016."
        )

    if "owner_sub" not in columns:
        op.add_column("portfolios", sa.Column("owner_sub", sa.String(), nullable=True))
    if "org_id" not in columns:
        op.add_column("portfolios", sa.Column("org_id", sa.String(), nullable=True))
    if owner_sub:
        bind.execute(
            sa.text(
                "UPDATE portfolios "
                "SET owner_sub = COALESCE(owner_sub, :owner_sub), "
                "    org_id = COALESCE(org_id, :org_id) "
                "WHERE owner_sub IS NULL"
            ),
            {"owner_sub": owner_sub, "org_id": org_id},
        )
    op.alter_column(
        "portfolios", "owner_sub", existing_type=sa.String(), nullable=False
    )

    uniques = {item["name"] for item in insp.get_unique_constraints("portfolios")}
    if "uq_portfolios_name" in uniques:
        op.drop_constraint("uq_portfolios_name", "portfolios", type_="unique")
    if "uq_portfolios_owner_sub_name" not in uniques:
        op.create_unique_constraint(
            "uq_portfolios_owner_sub_name", "portfolios", ["owner_sub", "name"]
        )

    indexes = {item["name"] for item in insp.get_indexes("portfolios")}
    if "ix_portfolios_owner_sub" not in indexes:
        op.create_index(
            "ix_portfolios_owner_sub", "portfolios", ["owner_sub"], unique=False
        )


def upgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    _ensure_optimize_jobs(insp)
    insp = sa.inspect(bind)
    _ensure_portfolio_owner_isolation(bind, insp)


def downgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)

    if "portfolios" in insp.get_table_names():
        indexes = {item["name"] for item in insp.get_indexes("portfolios")}
        uniques = {item["name"] for item in insp.get_unique_constraints("portfolios")}
        columns = {column["name"] for column in insp.get_columns("portfolios")}
        if "ix_portfolios_owner_sub" in indexes:
            op.drop_index("ix_portfolios_owner_sub", table_name="portfolios")
        if "uq_portfolios_owner_sub_name" in uniques:
            op.drop_constraint(
                "uq_portfolios_owner_sub_name", "portfolios", type_="unique"
            )
        if "uq_portfolios_name" not in uniques:
            op.create_unique_constraint("uq_portfolios_name", "portfolios", ["name"])
        if "org_id" in columns:
            op.drop_column("portfolios", "org_id")
        if "owner_sub" in columns:
            op.drop_column("portfolios", "owner_sub")

    if "optimize_jobs" in insp.get_table_names():
        indexes = {item["name"] for item in insp.get_indexes("optimize_jobs")}
        if "ix_optimize_jobs_kind_params_hash" in indexes:
            op.drop_index(
                "ix_optimize_jobs_kind_params_hash", table_name="optimize_jobs"
            )
        op.drop_table("optimize_jobs")
