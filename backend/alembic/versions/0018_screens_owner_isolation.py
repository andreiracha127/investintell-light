"""add owner isolation to saved screener screens

Revision ID: 0018
Revises: 0017

Adds owner_sub/org_id to persisted screener screens and replaces the global
UNIQUE(name) with UNIQUE(owner_sub, name). Existing single-tenant screens are
adopted by SCREENER_BOOTSTRAP_OWNER_SUB; fail loud when adoption is required
and the owner is not provided.
"""

import os

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0018"
down_revision: str | None = "0017"
branch_labels: str | None = None
depends_on: str | None = None

_OWNER_ENV = "SCREENER_BOOTSTRAP_OWNER_SUB"
_ORG_ENV = "SCREENER_BOOTSTRAP_ORG_ID"


def upgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    if "screens" not in insp.get_table_names():
        return

    columns = {column["name"] for column in insp.get_columns("screens")}
    existing_rows = bind.execute(sa.text("SELECT count(*) FROM screens")).scalar_one()
    owner_sub = os.getenv(_OWNER_ENV)
    org_id = os.getenv(_ORG_ENV)
    needs_owner_backfill = (
        "owner_sub" not in columns
        or bind.execute(
            sa.text("SELECT EXISTS (SELECT 1 FROM screens WHERE owner_sub IS NULL)")
        ).scalar_one()
    )
    if existing_rows and needs_owner_backfill and not owner_sub:
        raise RuntimeError(
            f"Set {_OWNER_ENV} to the JWT subject that should adopt the existing "
            "saved screener screens before running migration 0018."
        )

    if "owner_sub" not in columns:
        op.add_column("screens", sa.Column("owner_sub", sa.String(), nullable=True))
    if "org_id" not in columns:
        op.add_column("screens", sa.Column("org_id", sa.String(), nullable=True))

    if owner_sub:
        bind.execute(
            sa.text(
                "UPDATE screens "
                "SET owner_sub = COALESCE(owner_sub, :owner_sub), "
                "    org_id = COALESCE(org_id, :org_id) "
                "WHERE owner_sub IS NULL"
            ),
            {"owner_sub": owner_sub, "org_id": org_id},
        )

    op.alter_column("screens", "owner_sub", existing_type=sa.String(), nullable=False)

    uniques = {item["name"] for item in insp.get_unique_constraints("screens")}
    if "uq_screens_name" in uniques:
        op.drop_constraint("uq_screens_name", "screens", type_="unique")
    if "uq_screens_owner_sub_name" not in uniques:
        op.create_unique_constraint(
            "uq_screens_owner_sub_name", "screens", ["owner_sub", "name"]
        )

    indexes = {item["name"] for item in insp.get_indexes("screens")}
    if "ix_screens_owner_sub" not in indexes:
        op.create_index(
            "ix_screens_owner_sub", "screens", ["owner_sub"], unique=False
        )


def downgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    if "screens" not in insp.get_table_names():
        return

    indexes = {item["name"] for item in insp.get_indexes("screens")}
    uniques = {item["name"] for item in insp.get_unique_constraints("screens")}
    columns = {column["name"] for column in insp.get_columns("screens")}

    if "ix_screens_owner_sub" in indexes:
        op.drop_index("ix_screens_owner_sub", table_name="screens")
    if "uq_screens_owner_sub_name" in uniques:
        op.drop_constraint("uq_screens_owner_sub_name", "screens", type_="unique")
    if "uq_screens_name" not in uniques:
        op.create_unique_constraint("uq_screens_name", "screens", ["name"])
    if "org_id" in columns:
        op.drop_column("screens", "org_id")
    if "owner_sub" in columns:
        op.drop_column("screens", "owner_sub")
