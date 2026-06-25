"""ORM model for the screener read snapshot materialized view.

The request path should read this active-equity projection instead of joining
``universe_constituents`` to ``screener_metrics`` for every screen/build/result
request.
"""

from datetime import date, datetime

from sqlalchemy import Date, DateTime, String
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class ScreenerEquitySnapshot(Base):
    __tablename__ = "screener_equity_snapshot_mv"

    ticker: Mapped[str] = mapped_column(String, primary_key=True)
    name: Mapped[str | None] = mapped_column(String, nullable=True)
    sector: Mapped[str | None] = mapped_column(String, nullable=True)
    status: Mapped[str] = mapped_column(String, nullable=False)
    computed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    as_of: Mapped[date | None] = mapped_column(Date, nullable=True)

    ret_1w: Mapped[float | None] = mapped_column(nullable=True)
    ret_1m: Mapped[float | None] = mapped_column(nullable=True)
    ret_3m: Mapped[float | None] = mapped_column(nullable=True)
    ret_6m: Mapped[float | None] = mapped_column(nullable=True)
    ret_1y: Mapped[float | None] = mapped_column(nullable=True)
    ret_ytd: Mapped[float | None] = mapped_column(nullable=True)
    ret_mtd: Mapped[float | None] = mapped_column(nullable=True)

    vol_1m: Mapped[float | None] = mapped_column(nullable=True)
    vol_3m: Mapped[float | None] = mapped_column(nullable=True)
    vol_6m: Mapped[float | None] = mapped_column(nullable=True)
    vol_1y: Mapped[float | None] = mapped_column(nullable=True)

    beta_3m_spy: Mapped[float | None] = mapped_column(nullable=True)
    beta_6m_spy: Mapped[float | None] = mapped_column(nullable=True)
    beta_1y_spy: Mapped[float | None] = mapped_column(nullable=True)
    beta_2y_spy: Mapped[float | None] = mapped_column(nullable=True)

    corr_spy: Mapped[float | None] = mapped_column(nullable=True)
    corr_gld: Mapped[float | None] = mapped_column(nullable=True)
    corr_agg: Mapped[float | None] = mapped_column(nullable=True)
    corr_tlt: Mapped[float | None] = mapped_column(nullable=True)
    corr_uso: Mapped[float | None] = mapped_column(nullable=True)

    pct_above_sma20: Mapped[float | None] = mapped_column(nullable=True)
    pct_above_sma50: Mapped[float | None] = mapped_column(nullable=True)
    pct_above_sma200: Mapped[float | None] = mapped_column(nullable=True)

    price_close: Mapped[float | None] = mapped_column(nullable=True)
    avg_volume_1m: Mapped[float | None] = mapped_column(nullable=True)

    market_cap: Mapped[float | None] = mapped_column(nullable=True)
    pe_ratio: Mapped[float | None] = mapped_column(nullable=True)
    roe: Mapped[float | None] = mapped_column(nullable=True)
    roa: Mapped[float | None] = mapped_column(nullable=True)
    gross_margin: Mapped[float | None] = mapped_column(nullable=True)
    de_ratio: Mapped[float | None] = mapped_column(nullable=True)
    investment_growth: Mapped[float | None] = mapped_column(nullable=True)
    profitability_gross: Mapped[float | None] = mapped_column(nullable=True)
    fundamentals_period_end: Mapped[date | None] = mapped_column(Date, nullable=True)
