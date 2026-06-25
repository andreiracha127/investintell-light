"""ORM models for per-portfolio construction limits (Sprint B, Task 2).

Sprint B persists the construction constraints a portfolio was built under so
the save flow can record them and a CRUD endpoint can read them back. Two
tables, both single-tenant (scoped by ``portfolio_id``, no owner column — same
as the portfolio tables):

- ``portfolio_constraint_set`` — header, 1:1 with a portfolio. Holds the
  scalar limits (``cap``, ``min_weight``, ``overlap_cap``), each nullable
  (absent = no limit of that kind).
- ``portfolio_class_limits`` — zero-or-more per-asset-class min/max weight
  bounds, one row per (portfolio, asset_class). ``asset_class`` is
  CHECK-constrained to a fixed vocabulary.

Both children FK to ``portfolios.id`` with ON DELETE CASCADE: deleting a
portfolio drops its constraints. PKs follow the portfolio-family int
convention (NOT the uuid convention used by optimize_jobs).
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    Float,
    ForeignKey,
    Index,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base

# Allowed asset classes — kept in sync with the CHECK constraint below and the
# class-limit upsert in app/services/portfolio_constraints.py.
ASSET_CLASSES = ("equity", "fixed_income", "cash", "alternatives", "multi_asset")


class PortfolioConstraintSet(Base):
    """Header row holding the scalar construction limits for one portfolio."""

    __tablename__ = "portfolio_constraint_set"

    # 1:1 with a portfolio — the portfolio id IS the primary key. ON DELETE
    # CASCADE drops the constraint set when the portfolio is deleted.
    portfolio_id: Mapped[int] = mapped_column(
        ForeignKey("portfolios.id", ondelete="CASCADE"), primary_key=True
    )

    # Per-position weight cap (max single-holding weight); null = no cap.
    cap: Mapped[float | None] = mapped_column(Float, nullable=True)

    # Minimum per-position weight floor; null = no floor.
    min_weight: Mapped[float | None] = mapped_column(Float, nullable=True)

    # Maximum allowed look-through overlap between holdings; null = no limit.
    overlap_cap: Mapped[float | None] = mapped_column(Float, nullable=True)

    # Audit timestamps — tz-aware, server-set (same Core-update caveat as the
    # portfolio tables: a Core-level upsert must set updated_at explicitly).
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


class PortfolioClassLimit(Base):
    """Per-asset-class min/max weight bound for a portfolio."""

    __tablename__ = "portfolio_class_limits"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)

    portfolio_id: Mapped[int] = mapped_column(
        ForeignKey("portfolios.id", ondelete="CASCADE"), nullable=False
    )

    # One of ASSET_CLASSES; CHECK-constrained below.
    asset_class: Mapped[str] = mapped_column(String, nullable=False)

    # Lower/upper weight bound for the class; null = unbounded on that side.
    min_weight: Mapped[float | None] = mapped_column(Float, nullable=True)
    max_weight: Mapped[float | None] = mapped_column(Float, nullable=True)

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
        # One row per asset class within a portfolio — the upsert target.
        UniqueConstraint(
            "portfolio_id",
            "asset_class",
            name="uq_portfolio_class_limits_portfolio_id_asset_class",
        ),
        # Convention-expanded to ck_portfolio_class_limits_asset_class.
        CheckConstraint(
            "asset_class IN "
            "('equity', 'fixed_income', 'cash', 'alternatives', 'multi_asset')",
            name="asset_class",
        ),
        # Child-side FK index: lookups and the ON DELETE CASCADE scan by
        # portfolio_id.
        Index("ix_portfolio_class_limits_portfolio_id", "portfolio_id"),
    )
