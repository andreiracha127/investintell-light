"""rebalance_policies (Frente A — A1)

Revision ID: 0009
Revises: 0008

Política de rebalanceamento por portfólio (doc de research 2026-06-11 §2,
espelhando a mecânica LEAN: gatilho calendário + gatilho por banda de
tolerância + gatilho macro opcional, ortogonais e combináveis). Bandas em
frações decimais (0.05 = 5 p.p.; 0.25 = 25% do alvo). O produto é advisory:
nada aqui executa ordens — a política só parametriza quando o evaluator
gera proposta.
"""

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0009"
down_revision: str | None = "0008"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.create_table(
        "rebalance_policies",
        sa.Column("portfolio_id", sa.Integer(), nullable=False),
        sa.Column(
            "frequency", sa.String(), nullable=False, server_default="monthly"
        ),
        sa.Column("band_abs", sa.Float(), nullable=False, server_default="0.05"),
        sa.Column("band_rel", sa.Float(), nullable=False, server_default="0.25"),
        sa.Column(
            "macro_trigger_enabled",
            sa.Boolean(),
            nullable=False,
            server_default="false",
        ),
        sa.Column("last_evaluated_at", sa.DateTime(timezone=True), nullable=True),
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
        sa.ForeignKeyConstraint(
            ["portfolio_id"],
            ["portfolios.id"],
            name=op.f("fk_rebalance_policies_portfolio_id_portfolios"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint(
            "portfolio_id", name=op.f("pk_rebalance_policies")
        ),
        sa.CheckConstraint(
            "frequency IN ('weekly', 'monthly', 'quarterly')",
            name=op.f("ck_rebalance_policies_frequency"),
        ),
        sa.CheckConstraint(
            "band_abs > 0 AND band_abs <= 1",
            name=op.f("ck_rebalance_policies_band_abs"),
        ),
        sa.CheckConstraint(
            "band_rel > 0 AND band_rel <= 1",
            name=op.f("ck_rebalance_policies_band_rel"),
        ),
    )


def downgrade() -> None:
    op.drop_table("rebalance_policies")
