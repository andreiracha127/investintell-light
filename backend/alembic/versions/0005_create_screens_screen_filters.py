"""create screens and screen_filters (persisted screener screens, F6.4)

Revision ID: 0005
Revises: 0004

- screens — named, persisted screener screens (single-tenant, unique name).
- screen_filters — one row per (screen, metric_code) with nullable bounds
  (null = unbounded on that side) and a stable position for column ordering.
  ON DELETE CASCADE from screens.
"""

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0005"
down_revision: str | None = "0004"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.create_table(
        "screens",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("name", sa.String(), nullable=False),
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
        sa.PrimaryKeyConstraint("id", name="pk_screens"),
        sa.UniqueConstraint("name", name="uq_screens_name"),
    )

    op.create_table(
        "screen_filters",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("screen_id", sa.Integer(), nullable=False),
        sa.Column("metric_code", sa.String(), nullable=False),
        sa.Column("min_value", sa.Double(), nullable=True),
        sa.Column("max_value", sa.Double(), nullable=True),
        sa.Column("position", sa.Integer(), server_default="0", nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_screen_filters"),
        sa.ForeignKeyConstraint(
            ["screen_id"],
            ["screens.id"],
            name="fk_screen_filters_screen_id_screens",
            ondelete="CASCADE",
        ),
        sa.UniqueConstraint(
            "screen_id", "metric_code", name="uq_screen_filters_screen_id_metric_code"
        ),
    )
    op.create_index("ix_screen_filters_screen_id", "screen_filters", ["screen_id"])


def downgrade() -> None:
    op.drop_index("ix_screen_filters_screen_id", table_name="screen_filters")
    op.drop_table("screen_filters")
    op.drop_table("screens")
