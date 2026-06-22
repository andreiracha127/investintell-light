"""
ORM models for the local fund universe (F8.1).

All read-only; the fund snapshots are retired in favour of dynamic
VIEWs/MVs on Tiger (db/ddl/2026-06-13_dynamic_catalog.sql) derived live from
the source tables — never written in any request path:

- `funds_v` — identity + classification + fees, one row per eligible
  instrument_id (criterion: dispatch F8 §3 F8.1-2). Dynamic VIEW.
- `fund_risk_latest_mv` — latest fund_risk_metrics calc_date per instrument
  (precomputed; the Light NEVER recomputes). Materialized view.
- `nav_timeseries` — live daily NAV hypertable (the FundNav model reads it
  directly; the `fund_nav` snapshot is retired — Task 4.3).
- `fund_holdings_v` — latest N-PORT report per series, ranked by pct_of_nav.
  Dynamic VIEW; uncapped (the source is 100% of holdings — the profile route
  display-caps to top-50; the consolidated exposure comes from the data-lake
  look-through).
- `fund_classes_v` — share classes (DISTINCT ON class_id, latest period).
  Dynamic VIEW keyed by series_id (no instrument_id — readers resolve
  series→instrument through funds_v).
"""

import uuid
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    Integer,
    Numeric,
    String,
    Uuid,
)
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class Fund(Base):
    # Dynamic catalog VIEW (db/ddl/2026-06-13_dynamic_catalog.sql) — a faithful
    # SQL port of the retired sync_funds.py `funds` snapshot, derived live from
    # instrument_identity / sec_* / fund_risk_metrics / nav_timeseries on Tiger.
    # A view has no sync markers, so synced_at / source_calc_date /
    # source_nav_max_date are NOT columns here; the catalog service derives
    # staleness from the risk MV + NAV (Task 2.4 finalizes the staleness source).
    __tablename__ = "funds_v"

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
    # (manual_override first, otherwise latest proposed label per instrument) →
    # specific peer_strategy_label → 'Unclassified' (visible bucket, never NULL).
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


class FundBenchmarkCandidate(Base):
    """Resolved benchmark candidate for a fund series.

    Backed by ``fund_benchmark_candidates_v``. The view explains how a benchmark
    name was recovered from SEC registered-fund metadata and, when unambiguous,
    which canonical ETF proxy should be used for return/NAV comparisons.
    """

    __tablename__ = "fund_benchmark_candidates_v"

    series_id: Mapped[str] = mapped_column(String, primary_key=True)
    benchmark_name: Mapped[str | None] = mapped_column(String, nullable=True)
    benchmark_proxy_ticker: Mapped[str | None] = mapped_column(String, nullable=True)
    benchmark_proxy_instrument_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, nullable=True
    )
    benchmark_proxy_fit_quality_score: Mapped[Decimal | None] = mapped_column(
        Numeric, nullable=True
    )
    benchmark_proxy_asset_class: Mapped[str | None] = mapped_column(
        String, nullable=True
    )
    benchmark_resolution_method: Mapped[str | None] = mapped_column(
        String, nullable=True
    )
    benchmark_resolution_conflict: Mapped[bool] = mapped_column(
        Boolean, nullable=False
    )
    benchmark_proxy_candidates: Mapped[list[str]] = mapped_column(
        ARRAY(String), nullable=False
    )
    benchmark_canonical_name_matches: Mapped[list[str]] = mapped_column(
        ARRAY(String), nullable=False
    )


class FundClass(Base):
    """Share-class catalog (F8.6b) — dynamic VIEW over sec_fund_classes.

    The mother DB prices ONE instrument per fund series (a representative
    class, e.g. AGTHX for the Growth Fund of America); the remaining classes
    have NO NAV of their own in the source. Pricing/analysis of ANY class
    ticker therefore uses the series NAV (the representative class) as a
    PROXY — a documented approximation, also disclosed in the UI.

    Now backed by the fund_classes_v VIEW (db/ddl/2026-06-13_dynamic_catalog.sql,
    Task 2.5): DISTINCT ON (class_id) over sec_fund_classes, latest period per
    class. A class links to a fund via series_id — there is NO instrument_id
    column; readers resolve series→instrument through funds_v (the Fund model).
    """

    __tablename__ = "fund_classes_v"

    # SEC class id ('C000...') — globally unique in the source.
    class_id: Mapped[str] = mapped_column(String, primary_key=True)

    # Series the class belongs to (the NAV proxy anchor, joins to
    # funds_v.series_id). The source always carries it; nullable kept for the
    # ORM since a view has no NOT NULL enforcement.
    series_id: Mapped[str | None] = mapped_column(String, nullable=True, index=True)
    class_name: Mapped[str | None] = mapped_column(String, nullable=True)

    # Class ticker (e.g. RGAGX) — NOT NULL by the sync filter; indexed because
    # portfolio pricing resolves position tickers through this column.
    ticker: Mapped[str] = mapped_column(String, nullable=False, index=True)

    # Per-class expense ratio — a fraction (0.0069 = 0.69%), source
    # expense_ratio_pct is already fractional.
    expense_ratio: Mapped[Decimal | None] = mapped_column(Numeric, nullable=True)

    # xbrl_period_end of the filing the row was taken from (latest per class).
    source_period_end: Mapped[date | None] = mapped_column(Date, nullable=True)

    synced_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class FundRiskLatest(Base):
    # MV-backed (Tiger fund_risk_latest_mv): DISTINCT ON (instrument_id) of the
    # global (organization_id IS NULL) fund_risk_metrics, latest calc_date per
    # fund. Read-only; replaces the sync_funds.py snapshot. A MV is not a FK
    # target, so instrument_id is a plain PK (no ForeignKey to funds).
    __tablename__ = "fund_risk_latest_mv"

    instrument_id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True)

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
    cvar_999_evt: Mapped[Decimal | None] = mapped_column(Numeric, nullable=True)
    evt_xi_shape: Mapped[Decimal | None] = mapped_column(Numeric, nullable=True)
    volatility_garch: Mapped[Decimal | None] = mapped_column(Numeric, nullable=True)
    vol_model: Mapped[str | None] = mapped_column(String, nullable=True)
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
    # Class-specific regression metrics (Tier 1, rank 4) — read off the risk MV
    # (db/ddl/2026-06-13_dynamic_catalog.sql), computed by the risk_metrics
    # worker per asset_class. NULL for funds outside the matching class.
    empirical_duration: Mapped[Decimal | None] = mapped_column(Numeric, nullable=True)
    credit_beta: Mapped[Decimal | None] = mapped_column(Numeric, nullable=True)
    inflation_beta: Mapped[Decimal | None] = mapped_column(Numeric, nullable=True)
    crisis_alpha_score: Mapped[Decimal | None] = mapped_column(Numeric, nullable=True)

    # Active-share / overlap vs the fund's PRIMARY benchmark proxy (db-first A5).
    # Seeded onto fund_risk_metrics by the active-share worker and projected onto
    # fund_risk_latest_mv; read by the dossier instead of a standalone
    # fund_active_share_mv. All nullable — NULL means the fund is not covered.
    active_share_normalized: Mapped[Decimal | None] = mapped_column(Numeric, nullable=True)
    overlap_normalized: Mapped[Decimal | None] = mapped_column(Numeric, nullable=True)
    overlap_nav_raw: Mapped[Decimal | None] = mapped_column(Numeric, nullable=True)
    fund_cusip_coverage_nav: Mapped[Decimal | None] = mapped_column(Numeric, nullable=True)
    benchmark_cusip_coverage_nav: Mapped[Decimal | None] = mapped_column(
        Numeric, nullable=True
    )
    n_fund_holdings: Mapped[int | None] = mapped_column(Integer, nullable=True)
    n_benchmark_holdings: Mapped[int | None] = mapped_column(Integer, nullable=True)
    n_common_holdings: Mapped[int | None] = mapped_column(Integer, nullable=True)
    n_fund_only: Mapped[int | None] = mapped_column(Integer, nullable=True)
    n_benchmark_only: Mapped[int | None] = mapped_column(Integer, nullable=True)
    holdings_jaccard: Mapped[Decimal | None] = mapped_column(Numeric, nullable=True)
    fund_report_age_days: Mapped[int | None] = mapped_column(Integer, nullable=True)
    benchmark_report_age_days: Mapped[int | None] = mapped_column(Integer, nullable=True)
    report_date_gap_days: Mapped[int | None] = mapped_column(Integer, nullable=True)
    active_share_benchmark_instrument_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, nullable=True
    )
    active_share_benchmark_series_id: Mapped[str | None] = mapped_column(
        String, nullable=True
    )
    active_share_fund_report_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    active_share_benchmark_report_date: Mapped[date | None] = mapped_column(
        Date, nullable=True
    )


class FundListRow(Base):
    # MV-backed rowset for GET /funds. The dynamic funds_v lineage remains the
    # source of truth; this materialized projection removes expensive per-request
    # joins/sorts from the interactive list page.
    __tablename__ = "funds_list_mv"

    instrument_id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True)
    series_id: Mapped[str] = mapped_column(String, nullable=False, index=True)
    ticker: Mapped[str | None] = mapped_column(String, nullable=True)
    name: Mapped[str] = mapped_column(String, nullable=False)
    fund_type: Mapped[str] = mapped_column(String, nullable=False, index=True)
    strategy_label: Mapped[str] = mapped_column(String, nullable=False, index=True)
    asset_class: Mapped[str | None] = mapped_column(String, nullable=True, index=True)
    is_index: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    expense_ratio: Mapped[Decimal | None] = mapped_column(Numeric, nullable=True)
    aum_usd: Mapped[Decimal | None] = mapped_column(Numeric, nullable=True)
    inception_date: Mapped[date | None] = mapped_column(Date, nullable=True)

    calc_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    source_nav_max_date: Mapped[date | None] = mapped_column(Date, nullable=True)
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
    # Repointed (Task 4.3) to the LIVE nav_timeseries hypertable — the fund_nav
    # snapshot is retired (its sync was deleted in Task 4.2 and nothing writes it
    # anymore). nav_timeseries is a strict superset of the snapshot columns and is
    # UNIQUE on (instrument_id, nav_date), so the existing readers (optimizer
    # returns/eligibility, builder spots, portfolio latest-2) behave identically
    # without dedup. The class name stays FundNav (internal; renaming is out of
    # scope) — only the backing table changed.
    __tablename__ = "nav_timeseries"

    # Composite PK doubles as the (instrument_id, nav_date) lookup index.
    # nav_timeseries is a hypertable (not a FK target), so this is a plain PK
    # column (no ForeignKey).
    instrument_id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        primary_key=True,
    )
    nav_date: Mapped[date] = mapped_column(Date, primary_key=True)

    nav: Mapped[Decimal | None] = mapped_column(Numeric, nullable=True)
    return_1d: Mapped[Decimal | None] = mapped_column(Numeric, nullable=True)
    aum_usd: Mapped[Decimal | None] = mapped_column(Numeric, nullable=True)


class FundHolding(Base):
    # Dynamic VIEW (fund_holdings_v, db/ddl/2026-06-13_dynamic_catalog.sql,
    # Task 2.5): latest N-PORT report per series, ranked by pct_of_nav desc.
    # gics_sector is NULL::text in the source view (no resolved GICS column).
    __tablename__ = "fund_holdings_v"

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
    # N-PORT issuerCat code (CORP/UST/MUN...) — NOT a real sector.
    sector: Mapped[str | None] = mapped_column(String, nullable=True)
    # Real GICS sector via sec_cusip_ticker_map (exact CUSIP, fallback
    # issuer CUSIP-6); NULL when the issuer is outside the resolved map.
    gics_sector: Mapped[str | None] = mapped_column(String, nullable=True)
    market_value: Mapped[Decimal | None] = mapped_column(Numeric, nullable=True)
    pct_of_nav: Mapped[Decimal | None] = mapped_column(Numeric, nullable=True)
