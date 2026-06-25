"""ORM model for the ``portfolio_drift_status`` table (Sprint C, Task 1).

Sprint C adds a drift monitor: a daily worker evaluates each portfolio's
position-drift / asset-class / overlap breaches and persists the *latest*
status here — one row per portfolio. The endpoint and frontend read this row
back; the worker re-evaluates and upserts it each day.

The table is single-tenant (scoped by ``portfolio_id``, no owner column — same
as the portfolio / constraint tables). The portfolio id IS the primary key
(1:1 with a portfolio), FK to ``portfolios.id`` with ON DELETE CASCADE so
deleting a portfolio drops its drift status. The PK follows the portfolio-family
int convention (NOT the uuid convention used by optimize_jobs).
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Text, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base

# Allowed drift statuses, worst-first severity — kept in sync with the CHECK
# constraint below and the evaluation logic / service in
# app/services/portfolio_drift.py.
DRIFT_STATUSES = ("ok", "maintenance", "urgent")


class PortfolioDriftStatus(Base):
    """Latest drift evaluation for one portfolio (1:1 with a portfolio)."""

    __tablename__ = "portfolio_drift_status"

    # 1:1 with a portfolio — the portfolio id IS the primary key. ON DELETE
    # CASCADE drops the drift status when the portfolio is deleted.
    portfolio_id: Mapped[int] = mapped_column(
        ForeignKey("portfolios.id", ondelete="CASCADE"), primary_key=True
    )

    # When the worker last evaluated this portfolio's drift (tz-aware).
    evaluated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )

    # The worst severity across all breaches; CHECK-constrained to
    # DRIFT_STATUSES ('ok' when nothing is breached).
    worst_status: Mapped[str] = mapped_column(Text, nullable=False)

    # The full breach detail:
    #   {position_drifts: [...], class_breaches: [...], overlap_breaches: [...],
    #    overlap_report_date: <date-string|null>}
    breaches: Mapped[dict] = mapped_column(JSONB, nullable=False)

    # Audit timestamps — tz-aware, server-set. updated_at also bumps via
    # onupdate on ORM updates; the service stamps it explicitly too so a
    # Core-level update path stays correct (same caveat as the portfolio /
    # optimize_jobs tables).
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )

    __table_args__ = (
        # Convention-expanded to ck_portfolio_drift_status_worst_status.
        CheckConstraint(
            "worst_status IN ('ok', 'maintenance', 'urgent')",
            name="worst_status",
        ),
    )
