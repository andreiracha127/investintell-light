"""
ORM models for the `portfolios` and `positions` tables (F4).

A portfolio is a named, persisted collection of positions plus an uninvested
cash balance. Single-tenant: no owner column. Position tickers are validated
against Tiingo at the API layer (fail loud on typos) — deliberately NOT an FK
to `instruments` so a position never blocks instrument-cache maintenance.
"""

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, String, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base


class Portfolio(Base):
    __tablename__ = "portfolios"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)

    # Display name — unique across the (single-tenant) installation.
    name: Mapped[str] = mapped_column(String, nullable=False, unique=True)

    # Uninvested cash balance, in currency units.
    cash: Mapped[float] = mapped_column(nullable=False, server_default="0")

    # Audit timestamps — both tz-aware, server-set.
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    # NOTE: onupdate=func.now() fires only when SQLAlchemy ORM update statements
    # are emitted. Any Core-level UPDATE/upsert is invisible to this hook and
    # MUST set `updated_at=func.now()` explicitly (same rule as instruments).
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )

    # Positions collection — lazy="raise" per project conventions: load
    # explicitly via selectinload, never implicitly. passive_deletes=True
    # delegates child removal to the DB-level ON DELETE CASCADE so deleting a
    # portfolio never triggers a (forbidden) lazy load of the collection;
    # delete-orphan still covers in-session removals from a loaded collection.
    positions: Mapped[list["Position"]] = relationship(
        back_populates="portfolio",
        lazy="raise",
        cascade="all, delete-orphan",
        passive_deletes=True,
        order_by="Position.ticker",
    )


class Position(Base):
    __tablename__ = "positions"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)

    portfolio_id: Mapped[int] = mapped_column(
        ForeignKey("portfolios.id", ondelete="CASCADE"), nullable=False
    )

    # Canonical uppercase ticker — validated (regex + Tiingo existence) at the
    # API layer on the INSERT path.
    ticker: Mapped[str] = mapped_column(String, nullable=False)

    # Number of shares/units held; > 0 enforced at the API layer.
    quantity: Mapped[float] = mapped_column(nullable=False)

    # Acquisition price per share/unit — nullable: P&L renders null when absent.
    acq_price: Mapped[float | None] = mapped_column(nullable=True)

    # Audit timestamps — same conventions (and Core-update caveat) as Portfolio.
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

    portfolio: Mapped[Portfolio] = relationship(
        back_populates="positions", lazy="raise"
    )

    __table_args__ = (
        # One row per ticker within a portfolio — the PUT upsert target.
        UniqueConstraint(
            "portfolio_id", "ticker", name="uq_positions_portfolio_id_ticker"
        ),
        # Child-side FK index: selectinload of a portfolio's positions and the
        # ON DELETE CASCADE both scan by portfolio_id.
        Index("ix_positions_portfolio_id", "portfolio_id"),
    )
