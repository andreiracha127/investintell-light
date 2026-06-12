"""ORM model for the rebalance policy (Frente A — A1).

One optional policy row per portfolio. The evaluator NEVER auto-executes —
the policy only parameterizes when a re-optimization proposal is generated
(advisory product). Bands are decimal fractions, project-wide convention
(0.05 = 5 p.p. absolute; 0.25 = 25% of the target weight).
"""

from datetime import datetime

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    Float,
    ForeignKey,
    String,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class RebalancePolicy(Base):
    __tablename__ = "rebalance_policies"

    portfolio_id: Mapped[int] = mapped_column(
        ForeignKey("portfolios.id", ondelete="CASCADE"), primary_key=True
    )

    # Gatilho calendário: 'weekly' | 'monthly' (default) | 'quarterly'.
    frequency: Mapped[str] = mapped_column(
        String, nullable=False, server_default="monthly"
    )

    # Banda absoluta (p.p. do portfólio, fração decimal — default 5 p.p.).
    band_abs: Mapped[float] = mapped_column(
        Float, nullable=False, server_default="0.05"
    )
    # Banda relativa (% do peso-alvo, fração decimal — default 25%).
    band_rel: Mapped[float] = mapped_column(
        Float, nullable=False, server_default="0.25"
    )

    # Gatilho por evento de sinal (frente B): regime de stress de crédito.
    macro_trigger_enabled: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default="false"
    )

    # Carimbado pelo job agendado (scripts/evaluate_rebalance.py); o preview
    # on-demand NÃO carimba.
    last_evaluated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )

    __table_args__ = (
        CheckConstraint(
            "frequency IN ('weekly', 'monthly', 'quarterly')", name="frequency"
        ),
        CheckConstraint("band_abs > 0 AND band_abs <= 1", name="band_abs"),
        CheckConstraint("band_rel > 0 AND band_rel <= 1", name="band_rel"),
    )
