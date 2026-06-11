"""Response schemas for GET /stocks/{ticker}/analysis.

Scale contract (project-wide): every fractional quantity in this payload
(returns, volatility, VaR, CVaR, drawdown depth, change_pct, histogram bin
edges) is a decimal fraction (0.05 = 5%), never 0-100.

Time-series points are emitted as ``[iso_date, value]`` 2-tuples
(``tuple[dt.date, float]``): OpenAPI renders them as fixed-length arrays via
``prefixItems`` and openapi-typescript v7 turns those into ``[string, number]``
TypeScript tuples — directly consumable by ECharts without re-mapping. (This
was verified against the generated api.d.ts; if the generator ever degrades
tuples to plain arrays, switch to small ``{date, value}`` objects.)
"""

import datetime as dt
from typing import Literal

from pydantic import BaseModel, Field

RangeKey = Literal["1M", "6M", "1Y", "5Y", "MAX"]

# One time-series point: (date, value). Value scale depends on the series and
# is documented on each field that carries SeriesPoint lists.
SeriesPoint = tuple[dt.date, float]


class AnalysisParams(BaseModel):
    """Echo of the resolved request parameters."""

    range: RangeKey = Field(description="Requested range preset.")
    benchmark: str = Field(
        description="Benchmark ticker used for beta/correlation/relative series."
    )
    window: int = Field(description="Rolling window length in TRADING days.")
    start_date: dt.date = Field(
        description="Resolved visible-range start (inclusive for prices/candles)."
    )
    end_date: dt.date = Field(
        description="Resolved visible-range end — the last trading day available for the ticker."
    )


class AnalysisHeader(BaseModel):
    """Render-ready header strip values (RAW, un-adjusted prices)."""

    ticker: str
    name: str | None = Field(description="Instrument name from Tiingo metadata, if known.")
    last_close: float = Field(description="Most recent RAW close price (currency units).")
    prev_close: float = Field(
        description="Previous trading day's RAW close price (currency units)."
    )
    change: float = Field(
        description="last_close - prev_close, in currency units (not a fraction)."
    )
    change_pct: float = Field(
        description="One-day change as a decimal fraction (0.05 = 5%), never 0-100."
    )
    as_of: dt.date = Field(description="Date of last_close.")


class Candle(BaseModel):
    """One OHLCV candle built from RAW (un-adjusted) prices.

    Daily for ranges up to 5Y; weekly (W-FRI buckets: open=first, high=max,
    low=min, close=last, volume=sum) for range MAX.
    """

    date: dt.date
    open: float
    high: float
    low: float
    close: float
    volume: int


class CumulativeReturns(BaseModel):
    """Cumulative return series rebased to 0 at the first in-range date.

    Asset and benchmark share the same date grid (aligned on common trading
    days before slicing). Values are decimal fractions (0.05 = 5%), never
    0-100; both series start at exactly 0.0 on the same first date.
    """

    asset: list[SeriesPoint] = Field(
        description="[date, cumulative return] points; decimal fractions (0.05 = 5%)."
    )
    benchmark: list[SeriesPoint] = Field(
        description="[date, cumulative return] points; decimal fractions (0.05 = 5%)."
    )


class HistogramOut(BaseModel):
    """Histogram of in-range daily returns."""

    bin_edges: list[float] = Field(
        description="len(counts)+1 edges in daily-return units, decimal fractions (0.05 = 5%)."
    )
    counts: list[int] = Field(description="Observations per bin.")
    counts_normalized: list[float] = Field(
        description="Each count divided by the maximum count (0-1), for direct bar heights."
    )


class DrawdownOut(BaseModel):
    """Maximum drawdown of the in-range ADJUSTED close series."""

    depth: float = Field(
        description="NEGATIVE decimal fraction (-0.35 = 35% peak-to-trough loss), never 0-100."
    )
    peak_date: dt.date
    trough_date: dt.date


class DatedValue(BaseModel):
    """A single dated return observation."""

    date: dt.date
    value: float = Field(description="Daily return as a decimal fraction (0.05 = 5%), never 0-100.")


class AnalysisStats(BaseModel):
    """Point statistics over IN-RANGE returns only (the rolling warm-up pad
    is never included). Beta/correlation are versus the benchmark on the
    aligned in-range date grid."""

    annualized_volatility: float = Field(
        description="Annualized volatility as a decimal fraction (0.25 = 25%), never 0-100."
    )
    var_95: float = Field(
        description=(
            "Historical 1-day VaR at 95% as a POSITIVE decimal fraction "
            "(0.02 = 5% of days lose more than 2%), never 0-100."
        )
    )
    var_99: float = Field(
        description="Historical 1-day VaR at 99% as a POSITIVE decimal fraction, never 0-100."
    )
    cvar_95: float = Field(
        description=(
            "Historical 1-day CVaR (expected shortfall) at 95% as a POSITIVE decimal "
            "fraction, never 0-100."
        )
    )
    total_return: float = Field(
        description=(
            "Compounded in-range total return as a decimal fraction (0.5 = +50%), never 0-100."
        )
    )
    beta: float = Field(description="Beta vs benchmark over in-range aligned returns (unitless).")
    correlation: float = Field(
        description="Pearson correlation vs benchmark over in-range aligned returns (-1..1)."
    )
    max_drawdown: DrawdownOut
    best_day: DatedValue
    worst_day: DatedValue


class StockAnalysisResponse(BaseModel):
    """Render-ready single-call payload for the stock analysis page.

    The backend computes ALL finance; the frontend only draws. Every
    fractional field is a decimal fraction (0.05 = 5%), never 0-100.
    Rolling series are warmed up on a pre-range pad and then sliced to the
    visible range with NaN rows dropped, so they cover the visible range
    from (approximately) its first trading day.
    """

    params: AnalysisParams
    header: AnalysisHeader
    candles: list[Candle]
    cumulative_returns: CumulativeReturns
    rolling_volatility: list[SeriesPoint] = Field(
        description=(
            "[date, annualized volatility] points, decimal fractions (0.25 = 25%); "
            "in-range dates only, NaN warm-up rows dropped."
        )
    )
    rolling_beta: list[SeriesPoint] = Field(
        description="[date, beta vs benchmark] points (unitless); in-range, NaN rows dropped."
    )
    rolling_correlation: list[SeriesPoint] = Field(
        description="[date, correlation vs benchmark] points (-1..1); in-range, NaN rows dropped."
    )
    histogram: HistogramOut
    stats: AnalysisStats
