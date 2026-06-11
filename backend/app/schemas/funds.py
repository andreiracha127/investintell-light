"""Request/response schemas for the fund universe endpoints (F8.2).

Scale contract (project-wide): percent-like values are decimal fractions
(0.05 = 5%), copied verbatim from the mother DB — the Light NEVER recomputes.

Classification caveat (mother-DB inventory 2026-06-11): `strategy_label`
largely comes from the source's automatic description classifier, which has
visible errors. Every list/profile response carries a fixed
``classification_note`` so the UI can disclaim it.
"""

import datetime as dt
import uuid

from pydantic import BaseModel, ConfigDict

# Fixed disclaimer — the sync mirrors the source faithfully and we do not
# store per-row provenance, so the caveat applies to the whole column.
CLASSIFICATION_NOTE = (
    "Labels da fonte podem conter erros do classificador automático"
)


class FundsStaleness(BaseModel):
    """Global data-freshness markers (max over the synced universe)."""

    synced_at: dt.datetime | None
    source_calc_date: dt.date | None
    source_nav_max_date: dt.date | None


class FundListItem(BaseModel):
    """One row of the funds table: identity + headline risk metrics."""

    model_config = ConfigDict(from_attributes=True)

    instrument_id: uuid.UUID
    series_id: str
    ticker: str | None
    name: str
    fund_type: str
    strategy_label: str
    asset_class: str | None
    is_index: bool | None
    expense_ratio: float | None
    aum_usd: float | None
    return_1y: float | None
    volatility_1y: float | None
    sharpe_1y: float | None
    max_drawdown_1y: float | None
    peer_sharpe_pctl: float | None
    elite_flag: bool | None


class FundsListResponse(BaseModel):
    items: list[FundListItem]
    total: int
    page: int
    page_size: int
    staleness: FundsStaleness
    classification_note: str = CLASSIFICATION_NOTE


class FundRiskOut(BaseModel):
    """The full precomputed risk snapshot (latest calc_date in the source)."""

    model_config = ConfigDict(from_attributes=True)

    calc_date: dt.date
    return_1m: float | None
    return_3m: float | None
    return_1y: float | None
    return_3y_ann: float | None
    return_5y_ann: float | None
    volatility_1y: float | None
    max_drawdown_1y: float | None
    max_drawdown_3y: float | None
    sharpe_1y: float | None
    sharpe_3y: float | None
    sortino_1y: float | None
    calmar_ratio_3y: float | None
    alpha_1y: float | None
    beta_1y: float | None
    information_ratio_1y: float | None
    tracking_error_1y: float | None
    var_95_1m: float | None
    cvar_95_1m: float | None
    cvar_95_12m: float | None
    cvar_99_evt: float | None
    peer_strategy_label: str | None
    peer_sharpe_pctl: float | None
    peer_sortino_pctl: float | None
    peer_return_pctl: float | None
    peer_drawdown_pctl: float | None
    peer_count: int | None
    manager_score: float | None
    elite_flag: bool | None
    downside_capture_1y: float | None
    upside_capture_1y: float | None
    equity_correlation_252d: float | None


class FundNavPoint(BaseModel):
    """One decimated NAV observation (last 2 years, ~260 points)."""

    date: dt.date
    nav: float | None


class FundHoldingItem(BaseModel):
    """One N-PORT holding row. ⚠️ ``pct_of_nav`` is in PERCENT units in the
    source (11.62 = 11.62%) — unlike the risk metrics, which are fractions."""

    model_config = ConfigDict(from_attributes=True)

    rank: int
    issuer_name: str | None
    cusip: str | None
    isin: str | None
    asset_class: str | None
    sector: str | None
    market_value: float | None
    pct_of_nav: float | None


class FundHoldingsOut(BaseModel):
    """Latest N-PORT report for the fund's series (top-50 truncated source)."""

    report_date: dt.date | None
    items: list[FundHoldingItem]
    # Sum of the reported pct_of_nav (percent units) — visibly < 100 because
    # of the top-50 source cap.
    pct_of_nav_total: float | None
    is_top50_truncated: bool


class FundProfileResponse(BaseModel):
    """Full fund profile: identity + all risk metrics + NAV series + holdings."""

    model_config = ConfigDict(from_attributes=True)

    instrument_id: uuid.UUID
    series_id: str
    ticker: str | None
    isin: str | None
    cusip: str | None
    lei: str | None
    name: str
    fund_type: str
    strategy_label: str
    asset_class: str | None
    is_index: bool | None
    expense_ratio: float | None
    aum_usd: float | None
    primary_benchmark: str | None
    inception_date: dt.date | None
    domicile: str | None
    currency: str | None
    synced_at: dt.datetime
    source_calc_date: dt.date
    source_nav_max_date: dt.date
    risk: FundRiskOut | None
    nav: list[FundNavPoint]
    holdings: FundHoldingsOut
    classification_note: str = CLASSIFICATION_NOTE
