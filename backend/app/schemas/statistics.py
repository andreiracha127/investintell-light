"""Request/response schemas for the Statistics group (F5).

Endpoints: POST /statistics/scenario, /statistics/beta, /statistics/correlation,
/statistics/stock-correlation.

Scale contract (project-wide): every fractional quantity in this payload
(returns, weights, volatility, VaR, correlations, histogram bin edges) is a
decimal fraction (0.05 = 5%), never 0-100. NAV values are currency units.

Time-series points are emitted as ``[iso_date, value]`` 2-tuples (the same
``SeriesPoint`` convention as F2/F3) — typed arrays, NEVER embedded JSON
strings. Scatter points are ``[x, y]`` float 2-tuples.

Pseudo-asset pattern (the Tiingo dispatch mandate): ``AssetRef`` is a
discriminated union on ``kind`` — either a plain ticker or a persisted
portfolio replayed at its CURRENT quantities. One resolver in the service
turns either shape into a daily return series.
"""

import datetime as dt
from typing import Annotated, Literal

from pydantic import BaseModel, Field, field_validator, model_validator

from app.schemas._tickers import normalize_ticker as _normalize_ticker
from app.schemas.analysis import DatedValue, HistogramOut, SeriesPoint

DEFAULT_ROLLING_WINDOW = 63
MIN_ROLLING_WINDOW = 10
MAX_ROLLING_WINDOW = 252

# One scatter/regression point: (x, y) in daily-return units (decimal fractions).
ScatterPoint = tuple[float, float]


# ---------------------------------------------------------------------------
# Pseudo-asset reference (discriminated union on `kind`)
# ---------------------------------------------------------------------------


class TickerRef(BaseModel):
    """Pseudo-asset reference: a plain instrument ticker."""

    kind: Literal["ticker"]
    ticker: str = Field(description="Instrument ticker (normalized to uppercase).")

    @field_validator("ticker")
    @classmethod
    def _check_ticker(cls, value: str) -> str:
        return _normalize_ticker(value, "ticker")


class PortfolioRef(BaseModel):
    """Pseudo-asset reference: a persisted portfolio.

    Resolved by replaying the portfolio's CURRENT quantities over the request
    window (buy-and-hold historical replay — see ``app.analytics.portfolio``).
    The pseudo-asset's daily returns are the engine's ``portfolio_returns``
    over the inner-joined holdings (uninvested cash is NOT part of the
    pseudo-asset — it is constant and would only dilute beta/correlation).
    """

    kind: Literal["portfolio"]
    id: int = Field(ge=1, description="Persisted portfolio id.")


AssetRef = Annotated[TickerRef | PortfolioRef, Field(discriminator="kind")]


# ---------------------------------------------------------------------------
# Shared request bases
# ---------------------------------------------------------------------------


class _DateWindowRequest(BaseModel):
    """Base for explicit-window requests: start_date strictly before end_date."""

    start_date: dt.date = Field(description="Window start (inclusive).")
    end_date: dt.date = Field(description="Window end (inclusive).")

    @model_validator(mode="after")
    def _check_window(self) -> "_DateWindowRequest":
        if self.start_date >= self.end_date:
            raise ValueError(
                f"start_date ({self.start_date}) must be strictly before "
                f"end_date ({self.end_date})."
            )
        return self


class AssetPairRequest(_DateWindowRequest):
    """Two pseudo-assets compared over an explicit window."""

    asset_x: AssetRef = Field(description="X-axis / independent pseudo-asset.")
    asset_y: AssetRef = Field(description="Y-axis / dependent pseudo-asset.")


class AxisLabels(BaseModel):
    """Display labels for the two compared pseudo-assets."""

    x: str = Field(description="Label of asset_x: the ticker, or the portfolio name.")
    y: str = Field(description="Label of asset_y: the ticker, or the portfolio name.")


# ---------------------------------------------------------------------------
# POST /statistics/scenario
# ---------------------------------------------------------------------------


class ScenarioRequest(_DateWindowRequest):
    """Historical replay of a persisted portfolio over [start_date, end_date].

    Replay semantics: the portfolio's CURRENT quantities (and current cash)
    are held fixed over the whole window — "what would this portfolio have
    done over that period?", not a reconstruction of past trades.
    """

    portfolio_id: int = Field(ge=1, description="Persisted portfolio id.")


ScenarioFrequency = Literal["daily", "weekly"]


class StackedSeries(BaseModel):
    """One series of a stacked chart: a position ticker, "CASH", or "TOTAL"."""

    ticker: str = Field(
        description='Position ticker, "CASH" (constant cash balance), or "TOTAL".'
    )
    points: list[SeriesPoint] = Field(
        description="[date, value] points; the value scale is documented on the "
        "field that carries the series list."
    )


class DatedNav(BaseModel):
    """A single dated NAV observation, in currency units."""

    date: dt.date
    value: float = Field(description="Portfolio value in currency units (not a fraction).")


class ScenarioStatistics(BaseModel):
    """Typed statistics rail of the scenario — computed on DAILY data even when
    the line series are weekly-bounded. NAV figures include cash; returns are
    daily simple returns of the cash-inclusive total value."""

    start_date: dt.date = Field(description="First analyzed trading day.")
    end_date: dt.date = Field(description="Last analyzed trading day.")
    start_nav: float = Field(description="Total value (positions + cash) at start_date.")
    end_nav: float = Field(description="Total value (positions + cash) at end_date.")
    max_nav: DatedNav
    min_nav: DatedNav
    max_return: DatedValue = Field(description="Best daily return and its date.")
    min_return: DatedValue = Field(description="Worst daily return and its date.")
    annualized_volatility: float = Field(
        description="Annualized volatility of daily returns, decimal fraction (0.25 = 25%)."
    )
    var_95: float = Field(
        description="Historical 1-day VaR at 95% as a POSITIVE decimal fraction."
    )
    var_99: float = Field(
        description="Historical 1-day VaR at 99% as a POSITIVE decimal fraction."
    )


class ScenarioParams(BaseModel):
    """Echo of the resolved scenario parameters."""

    portfolio_id: int
    name: str = Field(description="Portfolio display name.")
    start_date: dt.date = Field(
        description="First analyzed trading day (first date where ALL holdings have data "
        "within the requested window)."
    )
    end_date: dt.date = Field(description="Last analyzed trading day.")
    cash: float = Field(description="Uninvested cash balance, in currency units.")
    frequency: ScenarioFrequency = Field(
        description="Grid of ALL emitted line series: daily, or weekly (W-FRI last-of-week) "
        "when the window exceeds the daily bounding threshold. Statistics stay daily."
    )


class ScenarioResponse(BaseModel):
    """Render-ready scenario payload — historical replay of a persisted portfolio.

    The portfolio's CURRENT quantities are held fixed (buy-and-hold) over the
    window; uninvested cash is a constant. All series share the same date grid
    (daily, or W-FRI weekly when bounded — see ``params.frequency``). The
    backend computes ALL finance; the frontend only draws.
    """

    params: ScenarioParams
    nav_cash: list[StackedSeries] = Field(
        description="Stacked value series in currency units: one per position, plus a "
        'constant "CASH" series when cash > 0, plus "TOTAL" (positions + cash).'
    )
    weights_percent: list[StackedSeries] = Field(
        description="Weight evolution as decimal fractions (0.5 = 50%, the frontend "
        'formats to 0-100): one per position, plus "CASH" when cash > 0. Rows sum '
        'to 1 across series per date. No "TOTAL" series (it would be constant 1).'
    )
    asset_performance: list[StackedSeries] = Field(
        description="Cumulative return rebased to 0.0 at the window start, decimal "
        'fractions: one per position, plus "TOTAL" (cash-inclusive portfolio).'
    )
    histogram: HistogramOut = Field(
        description="Histogram of the portfolio's DAILY returns (cash-inclusive total)."
    )
    statistics: ScenarioStatistics


# ---------------------------------------------------------------------------
# POST /statistics/beta
# ---------------------------------------------------------------------------


class BetaRequest(AssetPairRequest):
    """Regression of asset_y's daily returns on asset_x's over the window."""


class RegressionOut(BaseModel):
    """OLS regression of y on x over the aligned daily returns."""

    beta: float = Field(
        description="Slope: cov(x, y) / var(x) over aligned daily returns (engine beta)."
    )
    alpha: float = Field(
        description="Intercept in DAILY decimal-return units: mean_y - beta * mean_x, "
        "derived from the engine beta (NOT annualized)."
    )
    r: float = Field(description="Pearson correlation of the aligned returns (-1..1).")
    n_points: int = Field(description="Number of aligned daily return pairs.")


class BetaResponse(BaseModel):
    """Scatter + regression of two pseudo-assets' daily returns."""

    labels: AxisLabels
    scatter: list[ScatterPoint] = Field(
        description="[ret_x, ret_y] aligned daily return pairs, decimal fractions."
    )
    regression: RegressionOut
    regression_line: list[ScatterPoint] = Field(
        description="Two endpoints of the fitted line, y = alpha + beta * x evaluated "
        "at min(ret_x) and max(ret_x) — render-ready."
    )


# ---------------------------------------------------------------------------
# POST /statistics/correlation
# ---------------------------------------------------------------------------


class CorrelationRequest(AssetPairRequest):
    """Rolling correlation of two pseudo-assets' daily returns."""

    window: int = Field(
        default=DEFAULT_ROLLING_WINDOW,
        ge=MIN_ROLLING_WINDOW,
        le=MAX_ROLLING_WINDOW,
        description="Rolling window length in TRADING days.",
    )


class CorrelationResponse(BaseModel):
    """Rolling-correlation series of two pseudo-assets.

    Returns are warmed up on a pre-start lookback pad (the F2.2 pattern) so the
    series covers the requested window from (approximately) its first trading
    day; NaN warm-up rows are dropped.
    """

    labels: AxisLabels
    window: int = Field(description="Rolling window length in TRADING days.")
    series: list[SeriesPoint] = Field(
        description="[date, correlation] points (-1..1); in-range dates only."
    )
    current: float = Field(description="Most recent rolling correlation (last point).")


# ---------------------------------------------------------------------------
# POST /statistics/stock-correlation
# ---------------------------------------------------------------------------


class StockCorrelationRequest(BaseModel):
    """Pairwise correlation of a portfolio's holdings over a trailing window."""

    portfolio_id: int = Field(ge=1, description="Persisted portfolio id.")
    window: int = Field(
        default=DEFAULT_ROLLING_WINDOW,
        ge=MIN_ROLLING_WINDOW,
        le=MAX_ROLLING_WINDOW,
        description="Trailing window length in TRADING days of returns "
        "(window + 1 closes are required).",
    )
    end_date: dt.date | None = Field(
        default=None,
        description="Window end; defaults to the latest available trading day.",
    )


class StockCorrelationResponse(BaseModel):
    """Pairwise Pearson correlation matrix of the holdings' daily returns."""

    tickers: list[str] = Field(description="Row/column order of the matrix.")
    matrix: list[list[float]] = Field(
        description="Row-major square matrix (-1..1); symmetric with unit diagonal."
    )
    window: int = Field(description="Number of TRADING-day returns used (exactly).")
    as_of: dt.date = Field(
        description="Last trading day of the window (the latest date COMMON to all "
        "holdings, capped at the requested end_date)."
    )
