"""
ORM model for the `eod_prices` table (TimescaleDB hypertable).

Partition key is `date` — required to be part of any unique/PK constraint in
TimescaleDB. The composite PK (ticker, date) satisfies that constraint and
also serves as the idempotent upsert target used during ingestion.

No relationship() is defined here (YAGNI). If one is added later it MUST
use lazy="raise" per project conventions (see app/core/db.py).
"""

from datetime import date

from sqlalchemy import BigInteger, Date, ForeignKey, Index, String
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class EodPrice(Base):
    __tablename__ = "eod_prices"

    # Composite primary key — (ticker, date) uniquely identifies one price row.
    # `date` must be in the PK because it is the hypertable partition column.
    ticker: Mapped[str] = mapped_column(
        String,
        ForeignKey("instruments.ticker", ondelete="CASCADE"),
        primary_key=True,
    )
    date: Mapped[date] = mapped_column(Date, primary_key=True)

    # OHLCV (raw, un-adjusted).
    open: Mapped[float] = mapped_column(nullable=False)
    high: Mapped[float] = mapped_column(nullable=False)
    low: Mapped[float] = mapped_column(nullable=False)
    close: Mapped[float] = mapped_column(nullable=False)
    volume: Mapped[int] = mapped_column(BigInteger, nullable=False)

    # Adjusted OHLCV (split- and dividend-adjusted, sourced from Tiingo).
    adj_open: Mapped[float] = mapped_column(nullable=False)
    adj_high: Mapped[float] = mapped_column(nullable=False)
    adj_low: Mapped[float] = mapped_column(nullable=False)
    adj_close: Mapped[float] = mapped_column(nullable=False)
    adj_volume: Mapped[int] = mapped_column(BigInteger, nullable=False)

    # Corporate-action details — default values mean "no action".
    div_cash: Mapped[float] = mapped_column(nullable=False, server_default="0")
    split_factor: Mapped[float] = mapped_column(nullable=False, server_default="1")

    # Index on date alone enables efficient cross-sectional queries
    # (e.g. "all tickers on date X").
    __table_args__ = (Index("ix_eod_prices_date", "date"),)
