"""ORM model for the `screener_metrics` cross-sectional snapshot (F6.3).

One row per universe constituent, refreshed wholesale by the batch metrics
job (app/sync/metrics.py via scripts/compute_screener_metrics.py) — never
written in any request path.

NULL contract (deliberate contrast with the fail-loud analysis endpoints):
every metric column is nullable and NULL means "metric unavailable for this
ticker" — e.g. insufficient price history for the window, or a NULL/invalid
fundamentals input. The F2/F3 analysis endpoints fail loud because the user
asked for THAT ticker; the screener is cross-sectional — a ticker with three
months of history legitimately has ret_1y = NULL and simply cannot be ranked
on that metric.

Scale contract (project-wide): all fractional quantities (returns, vol,
pct_above_sma*, margins) are decimal fractions (0.05 = 5%), never 0-100.
"""

from datetime import date, datetime

from sqlalchemy import Date, DateTime, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class ScreenerMetrics(Base):
    __tablename__ = "screener_metrics"

    # One metrics row per constituent; removing a constituent removes its row.
    ticker: Mapped[str] = mapped_column(
        String,
        ForeignKey("universe_constituents.ticker", ondelete="CASCADE"),
        primary_key=True,
    )

    # When the job computed this row (tz-aware) and the EOD date the
    # price-derived metrics are anchored on (the ticker's last available date).
    computed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    as_of: Mapped[date] = mapped_column(Date, nullable=False)

    # --- Price-derived: trailing returns (calendar windows back from as_of) ---
    ret_1w: Mapped[float | None] = mapped_column(nullable=True)
    ret_1m: Mapped[float | None] = mapped_column(nullable=True)
    ret_3m: Mapped[float | None] = mapped_column(nullable=True)
    ret_6m: Mapped[float | None] = mapped_column(nullable=True)
    ret_1y: Mapped[float | None] = mapped_column(nullable=True)
    ret_ytd: Mapped[float | None] = mapped_column(nullable=True)
    ret_mtd: Mapped[float | None] = mapped_column(nullable=True)

    # --- Price-derived: annualized volatility over trailing windows ---
    vol_1m: Mapped[float | None] = mapped_column(nullable=True)
    vol_3m: Mapped[float | None] = mapped_column(nullable=True)
    vol_6m: Mapped[float | None] = mapped_column(nullable=True)
    vol_1y: Mapped[float | None] = mapped_column(nullable=True)

    # --- Price-derived: beta vs SPY over trailing windows ---
    beta_3m_spy: Mapped[float | None] = mapped_column(nullable=True)
    beta_6m_spy: Mapped[float | None] = mapped_column(nullable=True)
    beta_1y_spy: Mapped[float | None] = mapped_column(nullable=True)
    beta_2y_spy: Mapped[float | None] = mapped_column(nullable=True)

    # --- Price-derived: 1y correlation vs asset-class ETF proxies ---
    corr_spy: Mapped[float | None] = mapped_column(nullable=True)
    corr_gld: Mapped[float | None] = mapped_column(nullable=True)
    corr_agg: Mapped[float | None] = mapped_column(nullable=True)
    corr_tlt: Mapped[float | None] = mapped_column(nullable=True)
    corr_uso: Mapped[float | None] = mapped_column(nullable=True)

    # --- Price-derived: distance of adj_close above its SMA (close/SMA - 1) ---
    pct_above_sma20: Mapped[float | None] = mapped_column(nullable=True)
    pct_above_sma50: Mapped[float | None] = mapped_column(nullable=True)
    pct_above_sma200: Mapped[float | None] = mapped_column(nullable=True)

    # --- Price-derived: levels ---
    price_close: Mapped[float | None] = mapped_column(nullable=True)
    avg_volume_1m: Mapped[float | None] = mapped_column(nullable=True)

    # --- Fundamentals-derived (from fundamentals_snapshot RAW inputs) ---
    # market_cap = shares_outstanding x price_close (raw close at as_of).
    market_cap: Mapped[float | None] = mapped_column(nullable=True)
    # pe_ratio = market_cap / net_income_ttm; NULL when NI <= 0 — a
    # negative-earnings P/E is meaningless for screening.
    pe_ratio: Mapped[float | None] = mapped_column(nullable=True)
    # roe = net_income_ttm / book_equity; NULL when book_equity <= 0.
    roe: Mapped[float | None] = mapped_column(nullable=True)
    # roa = quality_roa carried through from the mother DB.
    roa: Mapped[float | None] = mapped_column(nullable=True)
    # gross_margin = gross_profit / revenue; NULL when revenue <= 0.
    gross_margin: Mapped[float | None] = mapped_column(nullable=True)
    # de_ratio = (total_assets - book_equity) / book_equity; NULL when
    # book_equity <= 0.
    de_ratio: Mapped[float | None] = mapped_column(nullable=True)
    # Carried through as-is from the mother DB snapshot.
    investment_growth: Mapped[float | None] = mapped_column(nullable=True)
    profitability_gross: Mapped[float | None] = mapped_column(nullable=True)
    # Fiscal period end of the fundamentals row the ratios were derived from.
    fundamentals_period_end: Mapped[date | None] = mapped_column(Date, nullable=True)
