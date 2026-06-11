"""Request/response schemas for POST /portfolio/analysis.

Scale contract (project-wide): every fractional quantity in this payload
(weights, returns, volatility, VaR, CVaR, drawdown depth, risk
contributions, histogram bin edges) is a decimal fraction (0.05 = 5%),
never 0-100.

Request validation is fail-loud with actionable messages: bad weights/
quantities/tickers are rejected with 422, never silently normalized away.
The only adjustment applied later (in the service) is renormalizing weights
that already pass the 1 +/- 1e-3 sum tolerance so the engine's exact-sum
guard is satisfied; the renormalized values are echoed in ``allocation``.
"""

import datetime as dt
import re
from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator

from app.schemas.analysis import (
    DatedValue,
    DrawdownOut,
    HistogramOut,
    RangeKey,
    SeriesPoint,
)

_TICKER_RE = re.compile(r"^[A-Z0-9.\-]{1,10}$")

MIN_POSITIONS = 2
MAX_POSITIONS = 50

# API-level tolerance on the weight sum (looser than the engine's 1e-6 guard;
# the service renormalizes within this band before calling the engine).
WEIGHT_SUM_TOLERANCE = 1e-3

PortfolioMode = Literal["weights", "quantities"]


def _normalize_ticker(value: str, label: str) -> str:
    symbol = value.strip().upper()
    if not _TICKER_RE.fullmatch(symbol):
        raise ValueError(
            f"Invalid {label} {value!r}: expected 1-10 characters from A-Z, 0-9, '.', '-'."
        )
    return symbol


class PositionIn(BaseModel):
    """One requested position: a ticker plus EITHER a weight OR a quantity.

    Which field is required depends on the request ``mode`` (cross-checked at
    the request level): mode=weights demands ``weight``, mode=quantities
    demands ``quantity``.
    """

    ticker: str = Field(description="Instrument ticker (normalized to uppercase).")
    weight: float | None = Field(
        default=None,
        description="Target weight as a decimal fraction (0.5 = 50%), never 0-100; > 0.",
    )
    quantity: float | None = Field(
        default=None, description="Number of shares/units held; > 0."
    )

    @field_validator("ticker")
    @classmethod
    def _check_ticker(cls, value: str) -> str:
        return _normalize_ticker(value, "ticker")


class PortfolioAnalysisRequest(BaseModel):
    """Ad-hoc portfolio definition to replay and decompose (no persistence)."""

    positions: list[PositionIn] = Field(
        min_length=MIN_POSITIONS,
        max_length=MAX_POSITIONS,
        description=f"Between {MIN_POSITIONS} and {MAX_POSITIONS} positions.",
    )
    mode: PortfolioMode = Field(
        description="'weights' = every position carries a weight; 'quantities' = share counts."
    )
    range: RangeKey = Field(
        default="1Y", description="Visible-range preset; MAX = full COMMON history."
    )
    benchmark: str = Field(
        default="SPY",
        description="Benchmark ticker for the comparison series and beta/correlation. "
        "May coincide with a position.",
    )

    @field_validator("benchmark")
    @classmethod
    def _check_benchmark(cls, value: str) -> str:
        return _normalize_ticker(value, "benchmark")

    @model_validator(mode="after")
    def _check_positions(self) -> "PortfolioAnalysisRequest":
        tickers = [p.ticker for p in self.positions]
        duplicates = sorted({t for t in tickers if tickers.count(t) > 1})
        if duplicates:
            raise ValueError(
                f"Duplicate tickers are not allowed: {', '.join(duplicates)}. "
                "Merge duplicate positions into one."
            )

        if self.mode == "weights":
            for position in self.positions:
                if position.weight is None:
                    raise ValueError(
                        f"mode='weights' requires a 'weight' on every position; "
                        f"{position.ticker} has none."
                    )
                if position.quantity is not None:
                    raise ValueError(
                        f"mode='weights' does not accept 'quantity'; "
                        f"{position.ticker} carries quantity={position.quantity}. "
                        "Use mode='quantities' or drop the quantity."
                    )
                if not position.weight > 0:
                    raise ValueError(
                        f"Weights must be > 0; {position.ticker} has weight={position.weight}."
                    )
            total = sum(p.weight for p in self.positions if p.weight is not None)
            if abs(total - 1.0) > WEIGHT_SUM_TOLERANCE:
                raise ValueError(
                    f"Weights must sum to 1 within {WEIGHT_SUM_TOLERANCE}; "
                    f"got {total}. Adjust the weights so they total 100%."
                )
        else:  # mode == "quantities"
            for position in self.positions:
                if position.quantity is None:
                    raise ValueError(
                        f"mode='quantities' requires a 'quantity' on every position; "
                        f"{position.ticker} has none."
                    )
                if position.weight is not None:
                    raise ValueError(
                        f"mode='quantities' does not accept 'weight'; "
                        f"{position.ticker} carries weight={position.weight}. "
                        "Use mode='weights' or drop the weight."
                    )
                if not position.quantity > 0:
                    raise ValueError(
                        f"Quantities must be > 0; {position.ticker} has "
                        f"quantity={position.quantity}."
                    )
        return self


class PortfolioParams(BaseModel):
    """Echo of the resolved request parameters."""

    mode: PortfolioMode
    range: RangeKey = Field(description="Requested range preset.")
    benchmark: str = Field(description="Benchmark ticker used for the comparison series.")
    start_date: dt.date = Field(
        description="First trading day of the analyzed window (first date where ALL "
        "position tickers have data)."
    )
    end_date: dt.date = Field(
        description="Last trading day of the analyzed window — the most recent date "
        "COMMON to all requested symbols (positions + benchmark). One stale symbol "
        "(a ticker whose last available EOD row lags the others) moves this date "
        "back for everyone; end = min(last_available_date per symbol)."
    )
    initial_nav: float = Field(
        description="Portfolio value at start_date, in currency units. 10000 for "
        "mode='weights' (notional); the actual position value for mode='quantities'."
    )


class AllocationPosition(BaseModel):
    """One position of the resolved allocation at the first date."""

    ticker: str
    weight: float = Field(
        description="Effective initial weight as a decimal fraction (0.5 = 50%), never "
        "0-100. For mode='weights' the (renormalized) requested weight; for "
        "mode='quantities' the initial-date value weight."
    )
    initial_value: float = Field(
        description="Position value at the first date, in currency units."
    )


class AllocationOut(BaseModel):
    """Resolved allocation at the first analyzed date (the replay strike point)."""

    positions: list[AllocationPosition]
    initial_nav: float = Field(
        description="Sum of initial position values, in currency units."
    )


class BenchmarkComparison(BaseModel):
    """Cumulative return of the portfolio vs the benchmark, rebased to 0.

    Both series share the same aligned date grid and start at exactly 0.0 on
    the same first date. Values are decimal fractions (0.05 = 5%), never 0-100.
    """

    portfolio: list[SeriesPoint] = Field(
        description="[date, cumulative return] points; decimal fractions (0.05 = 5%)."
    )
    benchmark: list[SeriesPoint] = Field(
        description="[date, cumulative return] points; decimal fractions (0.05 = 5%)."
    )


class CorrelationMatrixOut(BaseModel):
    """Pairwise Pearson correlation of per-asset daily returns."""

    tickers: list[str] = Field(description="Row/column order of the matrix.")
    matrix: list[list[float]] = Field(
        description="Row-major square matrix (-1..1); symmetric with unit diagonal."
    )


class RiskContributionOut(BaseModel):
    """One asset's share of total portfolio risk (CTR convention)."""

    ticker: str
    contribution: float = Field(
        description="Fraction of TOTAL portfolio risk (decimal fraction; all "
        "contributions sum to 1), evaluated at the effective initial weights."
    )


class PortfolioStats(BaseModel):
    """Point statistics over the portfolio's daily returns in the analyzed
    window. Beta/correlation are versus the benchmark on the aligned date
    grid; the diversification ratio is evaluated at the effective initial
    weights (decomposition view)."""

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
        description="Compounded total return of the replayed portfolio as a decimal "
        "fraction (0.5 = +50%), never 0-100."
    )
    beta: float = Field(
        description="Portfolio beta vs benchmark over aligned daily returns (unitless)."
    )
    correlation: float = Field(
        description="Pearson correlation vs benchmark over aligned daily returns (-1..1)."
    )
    diversification_ratio: float = Field(
        description="Weighted-average asset volatility divided by portfolio volatility "
        "at the effective initial weights; >= 1 for long-only portfolios (unitless)."
    )
    max_drawdown: DrawdownOut
    best_day: DatedValue
    worst_day: DatedValue


class PortfolioAnalysisResponse(BaseModel):
    """Render-ready single-call payload for the static portfolio page.

    Two views, two questions (see ``app.analytics.portfolio``): ``nav``,
    ``benchmark_comparison`` and the return-based ``stats`` are a buy-and-hold
    REPLAY (fixed quantities, weights drift); ``risk_contributions`` and
    ``diversification_ratio`` are a covariance DECOMPOSITION at the effective
    initial weights held constant. The backend computes ALL finance; the
    frontend only draws. Every fractional field is a decimal fraction
    (0.05 = 5%), never 0-100.
    """

    params: PortfolioParams
    allocation: AllocationOut
    nav: list[SeriesPoint] = Field(
        description="[date, NAV] points in currency units; starts at initial_nav. "
        "Daily up to 5Y; weekly (W-FRI, last-of-week) for range MAX. "
        "Shares the same date grid as benchmark_comparison (sliced to the "
        "portfolio–benchmark aligned index) so all line series can be plotted "
        "on a single x-axis. Stats are computed on the full position-grid NAV "
        "(before the benchmark alignment slice) — they describe the portfolio, "
        "not the comparison chart."
    )
    benchmark_comparison: BenchmarkComparison
    stats: PortfolioStats
    correlation_matrix: CorrelationMatrixOut
    risk_contributions: list[RiskContributionOut] = Field(
        description="Per-asset fractions of total risk; they sum to 1."
    )
    histogram: HistogramOut
