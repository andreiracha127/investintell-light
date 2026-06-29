"""Schemas for the P4 fund dossier Tier A endpoints.

Scale contract: return/risk fractions are decimal fractions (0.05 = 5%).
N-PORT holding/exposure percentages are percent points (50.0 = 50%), matching
the source views and look-through materialization.
"""

import datetime as dt
import uuid
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.analysis import (
    DatedValue,
    DrawdownOut,
    HistogramOut,
    RangeKey,
    SeriesPoint,
)
from app.schemas.funds import CLASSIFICATION_NOTE

ExposureSource = Literal["lookthrough", "holdings"]
VolatilityModel = Literal["garch", "ewma"]


class EmptyState(BaseModel):
    """Explicit reason why a real data source cannot populate a panel."""

    model_config = ConfigDict(extra="forbid")

    reason: str
    source: str | None = None


class FundAnalysisParams(BaseModel):
    """Echo of the resolved fund-analysis request parameters."""

    range: RangeKey = Field(description="Requested range preset.")
    window: int = Field(description="Rolling window length in trading/NAV days.")
    start_date: dt.date = Field(description="Resolved visible-range start date.")
    end_date: dt.date = Field(description="Latest NAV date used by the analysis.")


class FundAnalysisHeader(BaseModel):
    """Render-ready fund header values from NAV history."""

    instrument_id: uuid.UUID
    ticker: str | None
    name: str
    last_nav: float
    prev_nav: float
    change: float = Field(description="last_nav - prev_nav, in NAV units.")
    change_pct: float = Field(description="One-period NAV change as a decimal fraction.")
    as_of: dt.date


class FundAnalysisStats(BaseModel):
    """Point statistics over in-range daily NAV returns only."""

    annualized_volatility: float
    var_95: float
    cvar_95: float
    total_return: float
    max_drawdown: DrawdownOut
    best_day: DatedValue
    worst_day: DatedValue


class FundAnalysisResponse(BaseModel):
    """Single-call payload for the fund Performance dossier tab."""

    params: FundAnalysisParams
    header: FundAnalysisHeader
    growth_of_100: list[SeriesPoint] = Field(
        description="[date, value] growth series rebased to 100.0."
    )
    monthly_returns: list[SeriesPoint] = Field(
        description="[month_end, monthly return] points as decimal fractions."
    )
    rolling_volatility: list[SeriesPoint] = Field(
        description="[date, annualized volatility] points as decimal fractions."
    )
    rolling_sharpe: list[SeriesPoint] = Field(
        description="[date, rolling Sharpe] points using zero risk-free rate."
    )
    drawdown: list[SeriesPoint] = Field(
        description="[date, underwater drawdown] points as negative decimal fractions."
    )
    histogram: HistogramOut
    stats: FundAnalysisStats


class FundSectorExposure(BaseModel):
    """Sector exposure for Holdings tab bars/donut."""

    key: str
    label: str
    direct_pct: float
    indirect_pct: float
    total_pct: float
    source: ExposureSource


class FundTopHolding(BaseModel):
    """Top holding row enriched with a display sector label."""

    rank: int
    issuer_name: str | None
    cusip: str | None
    isin: str | None
    asset_class: str | None
    sector: str | None
    gics_sector: str | None
    sector_label: str | None
    market_value: float | None
    pct_of_nav: float | None


class FundHoldingsTopResponse(BaseModel):
    """Top holdings plus sector breakdown for one fund series."""

    instrument_id: uuid.UUID
    series_id: str
    report_date: dt.date | None
    top_holdings: list[FundTopHolding]
    sector_breakdown: list[FundSectorExposure]
    pct_of_nav_total: float | None


class FundPeerItem(BaseModel):
    """Peer row for the Peers dossier tab."""

    instrument_id: uuid.UUID
    ticker: str | None
    name: str
    strategy_label: str
    expense_ratio: float | None
    return_1y: float | None
    volatility_1y: float | None
    sharpe_1y: float | None
    max_drawdown_1y: float | None
    cvar_95_12m: float | None
    is_target: bool


class FundPeersResponse(BaseModel):
    """Funds in the same peer cohort as the target fund."""

    instrument_id: uuid.UUID
    cohort_label: str
    count: int
    items: list[FundPeerItem]
    classification_note: str = CLASSIFICATION_NOTE


class FundScatterResponse(BaseModel):
    """Columnar risk/return scatter payload for the funds landing page."""

    count: int
    instrument_ids: list[uuid.UUID]
    names: list[str]
    tickers: list[str | None]
    expected_returns: list[float]
    volatilities: list[float]
    tail_risks: list[float]
    strategies: list[str]
    classification_note: str = CLASSIFICATION_NOTE


# ---------------------------------------------------------------------------
# P5 Tier B dossier schemas
# ---------------------------------------------------------------------------


class FundSourceMetadata(BaseModel):
    """Source table and as-of information for DB-first dossier payloads."""

    model_config = ConfigDict(extra="forbid")

    source: str
    as_of: dt.date | None = None
    empty_state: EmptyState | None = None


class FundMarketSensitivity(BaseModel):
    """OLS beta of fund returns against one factor return series."""

    model_config = ConfigDict(extra="forbid")

    factor: str
    beta: float | None = None
    t_stat: float | None = None
    significance: str | None = None


class FundStyleBias(BaseModel):
    """Cross-sectional characteristic z-score for the latest available month."""

    model_config = ConfigDict(extra="forbid")

    factor: str
    value: float | None = None
    z_score: float | None = None
    as_of: dt.date | None = None


class FundFactorsResponse(BaseModel):
    """Market sensitivities and style-bias snapshot for one fund."""

    model_config = ConfigDict(extra="forbid")

    instrument_id: uuid.UUID
    market_sensitivities: list[FundMarketSensitivity]
    style_bias: list[FundStyleBias]
    source_metadata: list[FundSourceMetadata]


class FundStyleSectorWeight(BaseModel):
    """One sector bucket in one historical holdings period."""

    model_config = ConfigDict(extra="forbid")

    sector: str
    weight: float | None = Field(
        description="Sector weight as a decimal fraction (0.25 = 25%)."
    )


class FundStyleDriftPeriod(BaseModel):
    """Sector exposure for one N-PORT report date."""

    model_config = ConfigDict(extra="forbid")

    report_date: dt.date
    quarter: str
    sectors: list[FundStyleSectorWeight]


class FundStyleDriftResponse(BaseModel):
    """Historical sector weights from N-PORT reports."""

    model_config = ConfigDict(extra="forbid")

    instrument_id: uuid.UUID
    series_id: str
    periods: list[FundStyleDriftPeriod]
    empty_state: EmptyState | None = None


class FundDrawdownPeriod(BaseModel):
    """One peak-to-trough drawdown interval."""

    model_config = ConfigDict(extra="forbid")

    start_date: dt.date
    trough_date: dt.date
    end_date: dt.date | None = None
    depth: float
    duration_days: int
    recovery_days: int | None = None


class FundRiskStatistics(BaseModel):
    """Institutional risk statistics over the requested NAV window."""

    model_config = ConfigDict(extra="forbid")

    annualized_return: float | None = None
    annualized_volatility: float | None = None
    sharpe_ratio: float | None = None
    sortino_ratio: float | None = None
    calmar_ratio: float | None = None
    max_drawdown: float | None = None
    alpha: float | None = None
    beta: float | None = None
    tracking_error: float | None = None
    information_ratio: float | None = None
    n_observations: int


class FundDrawdownAnalysis(BaseModel):
    """Drawdown series and worst periods for the requested NAV window."""

    model_config = ConfigDict(extra="forbid")

    dates: list[dt.date]
    values: list[float]
    max_drawdown: float | None = None
    current_drawdown: float | None = None
    worst_periods: list[FundDrawdownPeriod]


class FundCaptureRatios(BaseModel):
    """Monthly up/down capture versus the requested benchmark."""

    model_config = ConfigDict(extra="forbid")

    up_capture: float | None = None
    down_capture: float | None = None
    up_periods: int = 0
    down_periods: int = 0
    benchmark_id: uuid.UUID | None = None
    benchmark_label: str | None = None
    empty_state: EmptyState | None = None


class FundRollingReturns(BaseModel):
    """Rolling compounded return series by window label."""

    model_config = ConfigDict(extra="forbid")

    series: dict[Literal["1M", "3M", "6M", "1Y"], list[SeriesPoint]]


class FundReturnDistribution(BaseModel):
    """Freedman-Diaconis histogram and distribution moments."""

    model_config = ConfigDict(extra="forbid")

    bin_edges: list[float]
    bin_counts: list[int]
    skewness: float | None = None
    kurtosis: float | None = None
    var_95: float | None = None
    cvar_95: float | None = None


class FundReturnStatistics(BaseModel):
    """eVestment-style return statistics over monthly returns."""

    model_config = ConfigDict(extra="forbid")

    arithmetic_mean_monthly: float | None = None
    geometric_mean_monthly: float | None = None
    avg_monthly_gain: float | None = None
    avg_monthly_loss: float | None = None
    gain_loss_ratio: float | None = None
    downside_deviation: float | None = None
    semi_deviation: float | None = None
    omega_ratio: float | None = None
    up_percentage_ratio: float | None = None
    down_percentage_ratio: float | None = None


class FundTailRiskMetrics(BaseModel):
    """Tail-risk ladder using parametric and Cornish-Fisher modified VaR."""

    model_config = ConfigDict(extra="forbid")

    var_parametric_90: float | None = None
    var_parametric_95: float | None = None
    var_parametric_99: float | None = None
    var_modified_95: float | None = None
    var_modified_99: float | None = None
    etl_95: float | None = None
    starr: float | None = None
    rachev: float | None = None
    jarque_bera: float | None = None
    jarque_bera_pvalue: float | None = None


class InsiderQuarterSentiment(BaseModel):
    """Quarterly Form 4 buy/sell aggregate for issuers held by the fund."""

    model_config = ConfigDict(extra="forbid")

    quarter: dt.date
    buy_value: float = 0.0
    sell_value: float = 0.0
    net_value: float = 0.0
    buy_count: int = 0
    sell_count: int = 0


class InsiderData(BaseModel):
    """Insider sentiment mapped from fund holdings to issuer CIKs."""

    model_config = ConfigDict(extra="forbid")

    issuer_ciks: list[str] = Field(default_factory=list)
    matched_cusips: list[str] = Field(default_factory=list)
    quarters: list[InsiderQuarterSentiment] = Field(default_factory=list)
    total_buy_value: float = 0.0
    total_sell_value: float = 0.0
    net_value: float = 0.0
    sentiment_score: float | None = Field(
        default=None,
        description="Net/(buy+sell), bounded to [-1, 1] when volume exists.",
    )
    source: str = "sec_insider_transactions"
    as_of: dt.date | None = None
    empty_state: EmptyState | None = None


class FundEntityAnalyticsResponse(BaseModel):
    """Deep Analysis modal payload for one fund."""

    model_config = ConfigDict(extra="forbid")

    instrument_id: uuid.UUID
    name: str
    as_of_date: dt.date
    window: Literal["3M", "6M", "1Y", "3Y", "5Y"]
    risk_statistics: FundRiskStatistics
    drawdown: FundDrawdownAnalysis
    capture: FundCaptureRatios
    rolling_returns: FundRollingReturns
    distribution: FundReturnDistribution
    return_statistics: FundReturnStatistics
    tail_risk: FundTailRiskMetrics
    insider_data: InsiderData | None = None


class InstitutionalHolder(BaseModel):
    """Institutional manager exposure across the fund's underlying CUSIPs."""

    model_config = ConfigDict(extra="forbid")

    cik: str
    manager_name: str
    value_usd: float | None = None
    shares: float | None = None
    holding_count: int = 0
    period: dt.date | None = None
    report_date: dt.date | None = None


class InstitutionalOverlapSecurity(BaseModel):
    """One fund holding with matching 13F institutional ownership."""

    model_config = ConfigDict(extra="forbid")

    cusip: str
    name: str | None = None
    fund_pct_of_nav: float | None = None
    institutional_value_usd: float | None = None
    institution_count: int = 0
    top_managers: list[str] = Field(default_factory=list)


class HolderNetworkNode(BaseModel):
    """Node for the Relationships modal holder/security network."""

    model_config = ConfigDict(extra="forbid")

    id: str
    label: str
    type: Literal["fund", "institution", "security"]
    value: float | None = None


class HolderNetworkEdge(BaseModel):
    """Edge for the Relationships modal holder/security network."""

    model_config = ConfigDict(extra="forbid")

    source: str
    target: str
    weight: float | None = None
    label: str | None = None


class HolderNetwork(BaseModel):
    """Small network payload for institutional relationships."""

    model_config = ConfigDict(extra="forbid")

    nodes: list[HolderNetworkNode]
    edges: list[HolderNetworkEdge]


class FundInstitutionalRevealResponse(BaseModel):
    """Tier C institutional reveal for one fund's underlying holdings."""

    model_config = ConfigDict(extra="forbid")

    instrument_id: uuid.UUID
    series_id: str
    fund_name: str
    holdings_report_date: dt.date | None = None
    period: dt.date | None = None
    top_holders: list[InstitutionalHolder]
    overlap: list[InstitutionalOverlapSecurity]
    holder_network: HolderNetwork
    empty_state: EmptyState | None = None


class ReverseLookupInstitution(BaseModel):
    """Institutional manager holding a requested CUSIP."""

    model_config = ConfigDict(extra="forbid")

    cik: str
    manager_name: str
    value_usd: float | None = None
    shares: float | None = None
    period: dt.date | None = None
    report_date: dt.date | None = None


class ReverseLookupFundExposure(BaseModel):
    """Fund/series exposure to a requested CUSIP from local N-PORT holdings."""

    model_config = ConfigDict(extra="forbid")

    instrument_id: uuid.UUID
    series_id: str
    ticker: str | None = None
    name: str
    issuer_name: str | None = None
    pct_of_nav: float | None = None
    market_value: float | None = None
    report_date: dt.date | None = None


class HoldingReverseLookupResponse(BaseModel):
    """Tier C reverse lookup from CUSIP to institutions and fund exposures."""

    model_config = ConfigDict(extra="forbid")

    cusip: str
    security_name: str | None = None
    period: dt.date | None = None
    institutions: list[ReverseLookupInstitution]
    fund_exposures: list[ReverseLookupFundExposure]
    empty_state: EmptyState | None = None


class FundRegimeBand(BaseModel):
    """One regime label point for the risk-timeseries overlay."""

    model_config = ConfigDict(extra="forbid")

    time: dt.date
    value: float
    regime: Literal["Expansion", "Cautious", "Stress"]


class FundRiskTimeseriesResponse(BaseModel):
    """Drawdown, conditional volatility, benchmark drawdown, and regime overlay series."""

    model_config = ConfigDict(extra="forbid")

    instrument_id: uuid.UUID
    drawdown: list[SeriesPoint] = Field(description="Drawdown in percent points.")
    conditional_volatility: list[SeriesPoint] = Field(
        description="Annualized conditional volatility in percent points."
    )
    benchmark_drawdown: list[SeriesPoint] = Field(
        default_factory=list,
        description="Benchmark drawdown in percent points, aligned to the requested risk window when available.",  # noqa: E501
    )
    benchmark_label: str | None = None
    benchmark_empty_state: EmptyState | None = None
    volatility_model: VolatilityModel
    regime_bands: list[FundRegimeBand]
    empty_state: EmptyState | None = None


class FundActiveShareResponse(BaseModel):
    """Holdings-based active share versus the fund's PRIMARY benchmark."""

    model_config = ConfigDict(extra="forbid")

    instrument_id: uuid.UUID
    benchmark_name: str | None = None
    benchmark_series_id: str | None = None
    active_share: float | None = None
    overlap: float | None = None
    n_portfolio_positions: int = 0
    n_benchmark_positions: int = 0
    n_common_positions: int = 0
    as_of_date: dt.date | None = None
    empty_state: EmptyState | None = None
