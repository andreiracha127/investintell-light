"""universe_constituents.sector — setor GICS por ticker

Revision ID: 0011
Revises: 0010

Setor real (GICS) por constituinte do universo do screener, populado pelo
scripts/enrich_sectors.py a partir de sec_cusip_ticker_map (data lake,
resolvida via OpenFIGI + Tiingo meta). NULL quando o ticker está fora do
mapa — o painel de setores da landing /stocks simplesmente o ignora.
"""

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0011"
down_revision: str | None = "0010"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.add_column(
        "universe_constituents",
        sa.Column("sector", sa.String(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("universe_constituents", "sector")
