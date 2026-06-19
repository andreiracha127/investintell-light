"""portfolio inception date

Revision ID: 0014
Revises: 0013

Store the user-declared portfolio inception date separately from created_at.
"""

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0014"
down_revision: str | None = "0013"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.add_column("portfolios", sa.Column("inception_date", sa.Date(), nullable=True))


def downgrade() -> None:
    op.drop_column("portfolios", "inception_date")
