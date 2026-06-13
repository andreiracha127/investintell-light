"""fund_risk_latest — métricas específicas por classe de fundo

Revision ID: 0012
Revises: 0011

A fund_risk_metrics do DB-mãe carrega passes de analytics por classe
(risk_calc): renda fixa (empirical_duration, credit_beta, yield_proxy_12m,
duration_adj_drawdown_1y), caixa/MMF (seven_day_net_yield, WAM, liquidez
semanal, NAV/share) e alternativos (crisis_alpha_score, inflation_beta).
``scoring_model`` identifica o pass que produziu a linha — a UI mostra
apenas o bloco aplicável à classe, em vez de "—" perpétuos.
"""

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0012"
down_revision: str | None = "0011"
branch_labels: str | None = None
depends_on: str | None = None

COLUMNS: tuple[sa.Column, ...] = (
    sa.Column("scoring_model", sa.String(), nullable=True),
    sa.Column("empirical_duration", sa.Numeric(), nullable=True),
    sa.Column("empirical_duration_r2", sa.Numeric(), nullable=True),
    sa.Column("credit_beta", sa.Numeric(), nullable=True),
    sa.Column("credit_beta_r2", sa.Numeric(), nullable=True),
    sa.Column("yield_proxy_12m", sa.Numeric(), nullable=True),
    sa.Column("duration_adj_drawdown_1y", sa.Numeric(), nullable=True),
    sa.Column("seven_day_net_yield", sa.Numeric(), nullable=True),
    sa.Column("fed_funds_rate_at_calc", sa.Numeric(), nullable=True),
    sa.Column("nav_per_share_mmf", sa.Numeric(), nullable=True),
    sa.Column("pct_weekly_liquid", sa.Numeric(), nullable=True),
    sa.Column("weighted_avg_maturity_days", sa.Integer(), nullable=True),
    sa.Column("crisis_alpha_score", sa.Numeric(), nullable=True),
    sa.Column("inflation_beta", sa.Numeric(), nullable=True),
    sa.Column("inflation_beta_r2", sa.Numeric(), nullable=True),
)


def upgrade() -> None:
    for column in COLUMNS:
        op.add_column("fund_risk_latest", column)


def downgrade() -> None:
    for column in reversed(COLUMNS):
        op.drop_column("fund_risk_latest", column.name)
