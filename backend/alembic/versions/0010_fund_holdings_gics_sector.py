"""fund_holdings.gics_sector — setor REAL por posição

Revision ID: 0010
Revises: 0009

N-PORT não tem setor: fund_holdings.sector guarda o issuerCat do filing
(CORP/UST/MUN...), que num fundo de ações é "CORP" em todas as linhas. O
setor real (GICS) vem de sec_cusip_ticker_map no data-lake (resolvida via
OpenFIGI + Tiingo meta), preenchido pelo sync F8.1 com match exato por
CUSIP e fallback por emissor (CUSIP-6). NULL quando o emissor está fora do
mapa (ex.: ações estrangeiras sem CUSIP mapeado).
"""

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0010"
down_revision: str | None = "0009"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.add_column(
        "fund_holdings",
        sa.Column("gics_sector", sa.String(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("fund_holdings", "gics_sector")
