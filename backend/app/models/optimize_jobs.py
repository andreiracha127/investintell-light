"""ORM model for the optimize_jobs table (E3 — async jobs).

NOTE (spec divergence): the DB-First spec says to "reuse" optimize_jobs, but the
table did not exist in this branch — it is CREATED here. A large walk-forward
backtest or a big monte-carlo enqueues a job (202 + polling) instead of blocking
the request; the runner writes ``result`` (jsonb) and the polling route serves it.
"""

from __future__ import annotations

import datetime as dt
import uuid

from sqlalchemy import CheckConstraint, DateTime, Integer, String, Uuid, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class OptimizeJob(Base):
    __tablename__ = "optimize_jobs"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    # Optional — portfolio-scoped jobs (scenario/stock-correlation/portfolio-MC).
    portfolio_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    kind: Mapped[str] = mapped_column(String, nullable=False)
    params_hash: Mapped[str] = mapped_column(String, nullable=False)
    status: Mapped[str] = mapped_column(String, nullable=False, server_default="pending")
    result: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    error: Mapped[str | None] = mapped_column(String, nullable=True)
    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False,
        server_default=func.now(), onupdate=func.now(),
    )

    __table_args__ = (
        CheckConstraint(
            "status IN ('pending', 'running', 'succeeded', 'failed')",
            name="status",
        ),
    )
