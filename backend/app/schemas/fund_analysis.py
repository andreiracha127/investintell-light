"""Schemas for the P4 fund dossier Tier A endpoints.

Scale contract: return/risk fractions are decimal fractions (0.05 = 5%).
N-PORT holding/exposure percentages are percent points (50.0 = 50%), matching
the source views and look-through materialization.
"""

import datetime as dt
import uuid
from typing import Literal

from pydantic import BaseModel, Field

from app.schemas.analysis import (
    DatedValue,
    DrawdownOut,
    HistogramOut,
    RangeKey,
    SeriesPoint,
)
from app.schemas.funds import CLASSIFICATION_NOTE

ExposureSource = Literal["lookthrough", "holdings"]


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
