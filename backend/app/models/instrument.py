"""
ORM model for the `instruments` table.

Each row represents one tradable ticker (equity, ETF, etc.) with metadata
sourced from Tiingo and staleness-tracking timestamps for incremental fetches.
"""

from datetime import date, datetime

from sqlalchemy import DateTime, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class Instrument(Base):
    __tablename__ = "instruments"

    # Canonical uppercase ticker symbol — primary key, sourced from Tiingo.
    ticker: Mapped[str] = mapped_column(String, primary_key=True)

    # Human-readable metadata (all nullable — may be absent for unlisted tickers).
    name: Mapped[str | None] = mapped_column(String, nullable=True)
    exchange_code: Mapped[str | None] = mapped_column(String, nullable=True)
    asset_type: Mapped[str | None] = mapped_column(String, nullable=True)

    # Tiingo coverage window for this ticker.
    tiingo_start_date: Mapped[date | None] = mapped_column(nullable=True)
    tiingo_end_date: Mapped[date | None] = mapped_column(nullable=True)

    # Staleness sentinel: set to now() after each successful EOD price fetch.
    # NULL means we have never fetched EOD data for this ticker.
    eod_last_fetched_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    # Audit timestamps — both tz-aware, server-set.
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
