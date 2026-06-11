"""
ORM models for the screener universe (F6).

- `universe_constituents` — the set of US equities the screener operates on,
  derived from the SEC company_tickers.json crosswalk joined (by CIK) against
  the mother DB's `company_characteristics_monthly` "active" CIK set.
- `fundamentals_snapshot` — latest RAW fundamentals row per ticker, copied
  from the mother DB by the sync service.  Derived ratios (P/E, ROE, ...) are
  deliberately NOT stored here — they are computed in F6.3 from these inputs.

Both tables are written ONLY by the batch sync (scripts/sync_universe.py) and
the backfill script (status updates) — never in any request path.
"""

from datetime import date, datetime

from sqlalchemy import BigInteger, Date, DateTime, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class UniverseConstituent(Base):
    __tablename__ = "universe_constituents"

    # Canonical uppercase ticker symbol (SEC spelling, e.g. BRK-B).
    ticker: Mapped[str] = mapped_column(String, primary_key=True)

    # SEC Central Index Key — the join key into the mother DB's fundamentals.
    # Indexed: F6.3+ joins/aggregations group by CIK (multi-class issuers).
    cik: Mapped[int] = mapped_column(BigInteger, nullable=False, index=True)

    # Company title as listed in SEC company_tickers.json.
    name: Mapped[str | None] = mapped_column(String, nullable=True)

    # Lifecycle: 'active' | 'no_tiingo_data' (backfill found no Tiingo coverage)
    # | 'excluded' (manually removed from the universe).
    # Indexed: the backfill and the metrics job both select WHERE status='active'.
    status: Mapped[str] = mapped_column(
        String, nullable=False, server_default="active", index=True
    )

    # Provenance of the constituent row, e.g. 'sec_company_tickers+mother_ccm'.
    source: Mapped[str] = mapped_column(String, nullable=False)

    # When the sync last touched this row (tz-aware, set by the sync run).
    synced_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )


class FundamentalsSnapshot(Base):
    __tablename__ = "fundamentals_snapshot"

    # One snapshot per constituent; removing a constituent removes its snapshot.
    ticker: Mapped[str] = mapped_column(
        String,
        ForeignKey("universe_constituents.ticker", ondelete="CASCADE"),
        primary_key=True,
    )

    # Always populated by the sync (the snapshot is fetched BY cik) — NOT NULL
    # since migration 0004.
    cik: Mapped[int] = mapped_column(BigInteger, nullable=False)

    # Fiscal period end of the latest fundamentals row in the mother DB.
    period_end: Mapped[date] = mapped_column(Date, nullable=False)

    # RAW inputs from company_characteristics_monthly (all nullable — the
    # mother DB has gaps; F6.3 must treat NULL as "metric unavailable").
    book_equity: Mapped[float | None] = mapped_column(nullable=True)
    total_assets: Mapped[float | None] = mapped_column(nullable=True)
    net_income_ttm: Mapped[float | None] = mapped_column(nullable=True)
    revenue: Mapped[float | None] = mapped_column(nullable=True)
    gross_profit: Mapped[float | None] = mapped_column(nullable=True)
    shares_outstanding: Mapped[float | None] = mapped_column(nullable=True)

    # Precomputed characteristics carried through as-is from the mother DB.
    quality_roa: Mapped[float | None] = mapped_column(nullable=True)
    investment_growth: Mapped[float | None] = mapped_column(nullable=True)
    profitability_gross: Mapped[float | None] = mapped_column(nullable=True)

    # Filing date of the SEC source document behind the fundamentals row.
    source_filing_date: Mapped[date | None] = mapped_column(Date, nullable=True)

    synced_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
