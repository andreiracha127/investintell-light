"""
ORM models for the `portfolios` and `positions` tables (F4).

A portfolio is a named, persisted collection of positions plus an uninvested
cash balance, scoped by the authenticated user's subject. Position tickers are
validated against Tiingo at the API layer (fail loud on typos) — deliberately
NOT an FK to `instruments` so a position never blocks instrument-cache
maintenance.
"""

from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Numeric,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base


class Portfolio(Base):
    __tablename__ = "portfolios"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)

    # Display name — unique per owner, not globally.
    name: Mapped[str] = mapped_column(String, nullable=False)

    # Auth tenant boundary. owner_sub is the stable JWT subject used for reads
    # and writes; org_id is stored for future organization-aware policy, but
    # current access checks remain user-sub scoped.
    owner_sub: Mapped[str] = mapped_column(String, nullable=False)
    org_id: Mapped[str | None] = mapped_column(String, nullable=True)

    # Uninvested cash balance, in currency units.
    cash: Mapped[float] = mapped_column(nullable=False, server_default="0")

    # Provenance: 'manual' (created via the CRUD UI) or 'builder'
    # (persisted from a builder proposal via POST /builder/save).
    origin: Mapped[str] = mapped_column(
        String, nullable=False, server_default="manual"
    )

    # User-declared inception date for performance/NAV presentation. This is
    # distinct from created_at, which is only the database row creation time.
    inception_date: Mapped[date | None] = mapped_column(Date, nullable=True)

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
    transactions: Mapped[list["PortfolioTransaction"]] = relationship(
        back_populates="portfolio",
        lazy="raise",
        cascade="all, delete-orphan",
        passive_deletes=True,
        order_by="PortfolioTransaction.trade_date, PortfolioTransaction.id",
    )
    nav_daily: Mapped[list["PortfolioNavDaily"]] = relationship(
        back_populates="portfolio",
        lazy="raise",
        cascade="all, delete-orphan",
        passive_deletes=True,
        order_by="PortfolioNavDaily.nav_date",
    )

    # The Base naming convention expands "origin" to "ck_portfolios_origin"
    # (matches migration 0007).
    __table_args__ = (
        UniqueConstraint(
            "owner_sub", "name", name="uq_portfolios_owner_sub_name"
        ),
        Index("ix_portfolios_owner_sub", "owner_sub"),
        CheckConstraint("origin IN ('manual', 'builder')", name="origin"),
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
    # basis='executed' positions store the EFFECTIVE cost basis here:
    # (fill_price * quantity + commission) / quantity.
    acq_price: Mapped[float | None] = mapped_column(nullable=True)

    # 'reference' — acq_price is a spot/NAV reference (analysis/sizing);
    # 'executed' — acq_price is a real fill incl. commissions (F8.6b).
    basis: Mapped[str] = mapped_column(
        String, nullable=False, server_default="reference"
    )

    # Total commission paid on the fill, currency units (>= 0); null when
    # unknown or basis='reference'.
    commission: Mapped[Decimal | None] = mapped_column(Numeric, nullable=True)

    # Execution date of the fill; null when unknown or basis='reference'.
    trade_date: Mapped[date | None] = mapped_column(Date, nullable=True)

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
        # Convention-expanded to ck_positions_basis /
        # ck_positions_commission_non_negative (matches migration 0007).
        CheckConstraint("basis IN ('reference', 'executed')", name="basis"),
        CheckConstraint(
            "commission IS NULL OR commission >= 0",
            name="commission_non_negative",
        ),
        # Child-side FK index: selectinload of a portfolio's positions and the
        # ON DELETE CASCADE both scan by portfolio_id.
        Index("ix_positions_portfolio_id", "portfolio_id"),
    )


class PortfolioTransaction(Base):
    """Immutable trade ledger entry for a persisted portfolio.

    ``positions`` remains the current snapshot. This table is the auditable
    source for transaction-aware NAV reconstruction.
    """

    __tablename__ = "portfolio_transactions"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    portfolio_id: Mapped[int] = mapped_column(
        ForeignKey("portfolios.id", ondelete="CASCADE"), nullable=False
    )
    ticker: Mapped[str] = mapped_column(String, nullable=False)
    side: Mapped[str] = mapped_column(String, nullable=False)
    quantity: Mapped[float] = mapped_column(nullable=False)
    price: Mapped[float] = mapped_column(nullable=False)
    commission: Mapped[Decimal] = mapped_column(
        Numeric, nullable=False, server_default="0"
    )
    trade_date: Mapped[date] = mapped_column(Date, nullable=False)
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
        back_populates="transactions", lazy="raise"
    )

    __table_args__ = (
        CheckConstraint("side IN ('buy', 'sell')", name="side"),
        CheckConstraint("quantity > 0", name="quantity_positive"),
        CheckConstraint("price > 0", name="price_positive"),
        CheckConstraint("commission >= 0", name="commission_non_negative"),
        Index(
            "ix_portfolio_transactions_portfolio_id_trade_date",
            "portfolio_id",
            "trade_date",
        ),
        Index("ix_portfolio_transactions_ticker_trade_date", "ticker", "trade_date"),
    )


class PortfolioNavDaily(Base):
    """Materialized daily NAV index for a persisted portfolio.

    The transaction ledger is the source of truth. This table is refreshed by
    the portfolio NAV worker so request paths can stay DB-first.
    """

    __tablename__ = "portfolio_nav_daily"

    portfolio_id: Mapped[int] = mapped_column(
        ForeignKey("portfolios.id", ondelete="CASCADE"), primary_key=True
    )
    nav_date: Mapped[date] = mapped_column(Date, primary_key=True)
    nav: Mapped[float] = mapped_column(nullable=False)
    market_value: Mapped[float] = mapped_column(nullable=False)
    cash: Mapped[float] = mapped_column(nullable=False)
    total_value: Mapped[float] = mapped_column(nullable=False)
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
        back_populates="nav_daily", lazy="raise"
    )

    __table_args__ = (
        CheckConstraint("nav > 0", name="nav_positive"),
        Index("ix_portfolio_nav_daily_nav_date", "nav_date"),
    )
