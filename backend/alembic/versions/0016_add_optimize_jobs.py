"""add optimize_jobs table (E3 — async jobs)

Revision ID: 0016
Revises: 0015

Spec divergence: the DB-First spec says to "reuse" optimize_jobs, but the table
did not exist in this branch. It is created here. The upgrade is guarded by an
existence check so it is idempotent if the table already exists in production
with a compatible shape.
"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0016"
down_revision: str | None = "0015"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    if "optimize_jobs" in insp.get_table_names():
        return  # tabela já existe em prod — não recriar (divergência da spec)
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


def downgrade() -> None:
    op.drop_index("ix_optimize_jobs_kind_params_hash", table_name="optimize_jobs")
    op.drop_table("optimize_jobs")
