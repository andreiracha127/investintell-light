"""drop fund_holdings.is_top50_truncated (Frente C — look-through)

Revision ID: 0008
Revises: 0007

O gate top-50 foi aposentado: a fonte N-PORT no data-lake passou a ser 100%
dos holdings (reingestão C0, ADENDO §6 do doc de research 2026-06-11) e o
sync local não trunca mais (MAX_HOLDINGS_PER_SERIES removido). A exposição
consolidada real vem das tabelas materializadas pelo worker
``nport_lookthrough`` no data-lake, consumidas por
GET /funds/{id}/lookthrough e GET /portfolios/{id}/lookthrough. A cobertura
por série (coverage_pct) vem de cagg_nport_series_profile via o summary do
look-through — nunca recalculada aqui.
"""

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0008"
down_revision: str | None = "0007"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.drop_column("fund_holdings", "is_top50_truncated")


def downgrade() -> None:
    op.add_column(
        "fund_holdings",
        sa.Column(
            "is_top50_truncated",
            sa.Boolean(),
            nullable=False,
            server_default="true",
        ),
    )
