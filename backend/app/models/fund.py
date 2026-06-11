"""
ORM models for the local fund universe (F8.1).

All four tables are read-only copies of mother-DB data, written ONLY by the
fund sync (scripts/sync_funds.py via app/sync/funds.py) — never in any
request path:

- `funds` — identity + classification + fees, one row per eligible
  instrument_id (criterion: dispatch F8 §3 F8.1-2).
- `fund_risk_latest` — snapshot of the latest fund_risk_metrics calc_date
  per instrument (precomputed in the mother DB; the Light NEVER recomputes).
- `fund_nav` — rolling daily NAV window (2 years + 30 days).
- `fund_holdings` — latest N-PORT report per series, ranked by pct_of_nav.
  ⚠️ the source is top-50 holdings per fund (is_top50_truncated).
"""

import uuid
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    ForeignKey,
    Integer,
    Numeric,
    String,
    Uuid,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class Fund(Base):
    __tablename__ = "funds"

    # Canonical mother-DB instrument UUID (instrument_identity.instrument_id).
    instrument_id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True)

    # SEC series id ('S000...') — NOT NULL by the eligibility criterion.
    # Indexed: fund_holdings joins by series_id; several share classes may
    # point at the same series.
    series_id: Mapped[str] = mapped_column(String, nullable=False, index=True)

    ticker: Mapped[str | None] = mapped_column(String, nullable=True)
    isin: Mapped[str | None] = mapped_column(String, nullable=True)
    cusip: Mapped[str | None] = mapped_column(String, nullable=True)
    lei: Mapped[str | None] = mapped_column(String, nullable=True)

    # Display name (cascade: registered/etf/mmf fund_name → universe name →
    # series_id as last resort, so never NULL).
    name: Mapped[str] = mapped_column(String, nullable=False)

    # 'etf' | 'mmf' (presence in sec_etfs / sec_money_market_funds) |
    # 'mutual_fund' otherwise — every eligible instrument is
    # instruments_universe.instrument_type = 'fund'.
    fund_type: Mapped[str] = mapped_column(String, nullable=False, index=True)

    # Strategy classification cascade (dispatch §3 F8.1-2, extended after the
    # source diagnosis): registered → etf → mmf → reclassification stage
    # (latest proposed label per instrument) → specific peer_strategy_label →
    # 'Unclassified' (visible bucket, never NULL).
    strategy_label: Mapped[str] = mapped_column(String, nullable=False, index=True)

    # Coarse asset class from instruments_universe
    # (equity / fixed_income / cash / alternatives — 100% coverage verified).
    asset_class: Mapped[str | None] = mapped_column(String, nullable=True, index=True)

    is_index: Mapped[bool | None] = mapped_column(Boolean, nullable=True)

    # net_operating_expenses preferred, fallback management_fee (cascade
    # registered → etf; see app/sync/funds.py).
    expense_ratio: Mapped[Decimal | None] = mapped_column(Numeric, nullable=True)

    # monthly_avg_net_assets; fallback = latest non-NULL aum_usd in the
    # synced NAV window.
    aum_usd: Mapped[Decimal | None] = mapped_column(Numeric, nullable=True)

    primary_benchmark: Mapped[str | None] = mapped_column(String, nullable=True)
    inception_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    domicile: Mapped[str | None] = mapped_column(String, nullable=True)
    currency: Mapped[str | None] = mapped_column(String, nullable=True)

    # Staleness fields (dispatch §3 F8.1-4) — exposed via the API in F8.2.
    synced_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    # Latest fund_risk_metrics.calc_date in the source at sync time.
    source_calc_date: Mapped[date] = mapped_column(Date, nullable=False)
    # Latest nav_timeseries.nav_date in the source at sync time.
    source_nav_max_date: Mapped[date] = mapped_column(Date, nullable=False)


class FundRiskLatest(Base):
    __tablename__ = "fund_risk_latest"

    instrument_id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        ForeignKey("funds.instrument_id", ondelete="CASCADE"),
        primary_key=True,
    )

    calc_date: Mapped[date] = mapped_column(Date, nullable=False)

    # Precomputed metrics copied verbatim from the latest fund_risk_metrics
    # row (all nullable — the mother DB has per-metric gaps).
    return_1m: Mapped[Decimal | None] = mapped_column(Numeric, nullable=True)
    return_3m: Mapped[Decimal | None] = mapped_column(Numeric, nullable=True)
    return_1y: Mapped[Decimal | None] = mapped_column(Numeric, nullable=True)
    return_3y_ann: Mapped[Decimal | None] = mapped_column(Numeric, nullable=True)
    return_5y_ann: Mapped[Decimal | None] = mapped_column(Numeric, nullable=True)
    volatility_1y: Mapped[Decimal | None] = mapped_column(Numeric, nullable=True)
    max_drawdown_1y: Mapped[Decimal | None] = mapped_column(Numeric, nullable=True)
    max_drawdown_3y: Mapped[Decimal | None] = mapped_column(Numeric, nullable=True)
    sharpe_1y: Mapped[Decimal | None] = mapped_column(Numeric, nullable=True)
    sharpe_3y: Mapped[Decimal | None] = mapped_column(Numeric, nullable=True)
    sortino_1y: Mapped[Decimal | None] = mapped_column(Numeric, nullable=True)
    calmar_ratio_3y: Mapped[Decimal | None] = mapped_column(Numeric, nullable=True)
    alpha_1y: Mapped[Decimal | None] = mapped_column(Numeric, nullable=True)
    beta_1y: Mapped[Decimal | None] = mapped_column(Numeric, nullable=True)
    information_ratio_1y: Mapped[Decimal | None] = mapped_column(Numeric, nullable=True)
    tracking_error_1y: Mapped[Decimal | None] = mapped_column(Numeric, nullable=True)
    var_95_1m: Mapped[Decimal | None] = mapped_column(Numeric, nullable=True)
    cvar_95_1m: Mapped[Decimal | None] = mapped_column(Numeric, nullable=True)
    cvar_95_12m: Mapped[Decimal | None] = mapped_column(Numeric, nullable=True)
    cvar_99_evt: Mapped[Decimal | None] = mapped_column(Numeric, nullable=True)
    peer_strategy_label: Mapped[str | None] = mapped_column(String, nullable=True)
    peer_sharpe_pctl: Mapped[Decimal | None] = mapped_column(Numeric, nullable=True)
    peer_sortino_pctl: Mapped[Decimal | None] = mapped_column(Numeric, nullable=True)
    peer_return_pctl: Mapped[Decimal | None] = mapped_column(Numeric, nullable=True)
    peer_drawdown_pctl: Mapped[Decimal | None] = mapped_column(Numeric, nullable=True)
    peer_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    manager_score: Mapped[Decimal | None] = mapped_column(Numeric, nullable=True)
    elite_flag: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    downside_capture_1y: Mapped[Decimal | None] = mapped_column(Numeric, nullable=True)
    upside_capture_1y: Mapped[Decimal | None] = mapped_column(Numeric, nullable=True)
    equity_correlation_252d: Mapped[Decimal | None] = mapped_column(Numeric, nullable=True)


class FundNav(Base):
    __tablename__ = "fund_nav"

    # Composite PK doubles as the (instrument_id, nav_date) lookup index.
    instrument_id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        ForeignKey("funds.instrument_id", ondelete="CASCADE"),
        primary_key=True,
    )
    nav_date: Mapped[date] = mapped_column(Date, primary_key=True)

    nav: Mapped[Decimal | None] = mapped_column(Numeric, nullable=True)
    return_1d: Mapped[Decimal | None] = mapped_column(Numeric, nullable=True)
    aum_usd: Mapped[Decimal | None] = mapped_column(Numeric, nullable=True)


class FundHolding(Base):
    __tablename__ = "fund_holdings"

    # Keyed by series (not instrument): share classes share one portfolio.
    # No FK to funds — series_id is not unique there (multi-class series).
    series_id: Mapped[str] = mapped_column(String, primary_key=True)
    report_date: Mapped[date] = mapped_column(Date, primary_key=True)
    # 1-based, ordered by pct_of_nav descending (NULL pct sorts last).
    rank: Mapped[int] = mapped_column(Integer, primary_key=True)

    issuer_name: Mapped[str | None] = mapped_column(String, nullable=True)
    cusip: Mapped[str | None] = mapped_column(String, nullable=True)
    isin: Mapped[str | None] = mapped_column(String, nullable=True)
    asset_class: Mapped[str | None] = mapped_column(String, nullable=True)
    sector: Mapped[str | None] = mapped_column(String, nullable=True)
    market_value: Mapped[Decimal | None] = mapped_column(Numeric, nullable=True)
    pct_of_nav: Mapped[Decimal | None] = mapped_column(Numeric, nullable=True)

    # The N-PORT source keeps only the top-50 holdings per fund — every row
    # carries this disclaimer flag (always true in v1).
    is_top50_truncated: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default="true"
    )
