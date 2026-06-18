"""Request/response schemas for POST /monte-carlo/projection.

Scale contract (project-wide): drawdown and annualized-return percentiles are
decimal fractions (0.05 = 5%), never 0-100; Sharpe is unitless. Request
validation is fail-loud (422 via Pydantic); the service maps analytics
ValueErrors to 422 as well.
"""

from typing import Annotated, Literal

from pydantic import BaseModel, Field, field_validator

from app.schemas._tickers import normalize_ticker as _normalize_ticker
from app.schemas.analysis import RangeKey
from app.schemas.builder import AssetRefIn

MIN_SIMULATIONS = 1_000
MAX_SIMULATIONS = 50_000

Statistic = Literal["max_drawdown", "return", "sharpe"]


class MonteCarloRequest(BaseModel):
    """Block-bootstrap Monte Carlo projection request for one instrument."""

    ticker: str = Field(description="Instrument ticker (normalized to uppercase).")
    statistic: Statistic = Field(
        default="max_drawdown",
        description="Which statistic to project: max_drawdown | return | sharpe.",
    )
    range: RangeKey = Field(
        default="MAX",
        description="History window used to estimate the return distribution; "
        "MAX = full available history.",
    )
    n_simulations: int = Field(
        default=10_000,
        ge=MIN_SIMULATIONS,
        le=MAX_SIMULATIONS,
        description=f"Number of bootstrap paths ({MIN_SIMULATIONS}-{MAX_SIMULATIONS}).",
    )
    horizons: list[int] | None = Field(
        default=None,
        description="Trading-day horizons for the confidence fan; default 1Y/3Y/5Y/7Y/10Y.",
    )
    risk_free_rate: float = Field(
        default=0.04,
        description="Annualized risk-free rate for the Sharpe statistic (decimal fraction).",
    )
    seed: int | None = Field(
        default=None, description="Optional RNG seed for a reproducible projection."
    )

    @field_validator("ticker")
    @classmethod
    def _check_ticker(cls, value: str) -> str:
        return _normalize_ticker(value, "ticker")

    @field_validator("horizons")
    @classmethod
    def _check_horizons(cls, value: list[int] | None) -> list[int] | None:
        if value is None:
            return None
        if len(value) == 0:
            raise ValueError("horizons must be non-empty when supplied")
        if any(h < 1 for h in value):
            raise ValueError("horizons must all be >= 1 trading day")
        return value


class MonteCarloParams(BaseModel):
    """Echo of the resolved request parameters."""

    ticker: str
    statistic: Statistic
    range: RangeKey
    n_simulations: int
    risk_free_rate: float
    seed: int | None = Field(description="Seed used, or null when unseeded.")


class ConfidenceBar(BaseModel):
    """One horizon's percentile fan of the projected statistic.

    For max_drawdown/return the percentile fields are decimal fractions
    (0.05 = 5%); for sharpe they are unitless.
    """

    horizon: str = Field(description="Human label, e.g. '1Y', '10Y' (or 'ND' for sub-year).")
    horizon_days: int = Field(description="Horizon length in trading days.")
    pct_5: float
    pct_10: float
    pct_25: float
    pct_50: float
    pct_75: float
    pct_90: float
    pct_95: float
    mean: float


class MonteCarloResponse(BaseModel):
    """Render-ready Monte Carlo projection payload.

    The backend computes ALL finance; the frontend only draws. Percentiles for
    max_drawdown/return are decimal fractions (0.05 = 5%); sharpe is unitless.
    """

    params: MonteCarloParams
    percentiles: dict[str, float] = Field(
        description="Distribution of the statistic at the longest horizon, keyed by "
        "percentile ('1st'..'99th')."
    )
    mean: float
    median: float
    std: float
    historical_value: float = Field(
        description="The statistic computed on the ACTUAL historical series."
    )
    historical_horizon_days: int = Field(
        description="Length of the historical series in trading days."
    )
    historical_percentile_rank: float | None = Field(
        description="Percentile rank (0-100) of the historical value within a "
        "horizon-matched bootstrap; null for the sharpe statistic."
    )
    confidence_bars: list[ConfidenceBar] = Field(
        description="Per-horizon percentile fans (the projection chart)."
    )
    degraded: bool = Field(
        description="True only when a flat-NAV Sharpe collapse made the result uninformative."
    )
    degraded_reason: str | None = Field(
        description="Diagnostic when degraded is True, else null."
    )


# -- Portfolio Monte Carlo (POST /monte-carlo/portfolio) -----------------------


class PortfolioPositionIn(BaseModel):
    """One position in a synthetic portfolio MC request.

    ``asset`` reuses the builder ref (FundRefIn | EquityRefIn) so the request is
    the exact weight list the optimizer returned; ``weight`` is a decimal
    fraction (0 < w <= 1). The service aligns weights to the loaded return
    frame's columns by the 'fund:{id}' / 'equity:{TICKER}' label scheme.
    """

    asset: AssetRefIn
    weight: Annotated[float, Field(gt=0, le=1, allow_inf_nan=False)]


class PortfolioMonteCarloRequest(BaseModel):
    """Block-bootstrap Monte Carlo over a synthetic portfolio NAV.

    The service builds ``portfolio_returns = frame @ w`` from the common-history
    aligned returns of the positions (target weights held = implicit continuous
    rebalancing), then runs the SAME pure ``block_bootstrap_monte_carlo`` the
    single-instrument projection uses.
    """

    positions: Annotated[list[PortfolioPositionIn], Field(min_length=2, max_length=50)]
    statistic: Statistic = Field(
        default="max_drawdown",
        description="Which statistic to project: max_drawdown | return | sharpe.",
    )
    n_simulations: int = Field(
        default=10_000,
        ge=MIN_SIMULATIONS,
        le=MAX_SIMULATIONS,
        description=f"Number of bootstrap paths ({MIN_SIMULATIONS}-{MAX_SIMULATIONS}).",
    )
    horizons: list[int] | None = Field(
        default=None,
        description="Trading-day horizons for the confidence fan; default 1Y/3Y/5Y/7Y/10Y.",
    )
    risk_free_rate: float = Field(
        default=0.04,
        description="Annualized risk-free rate for the Sharpe statistic (decimal fraction).",
    )
    seed: int | None = Field(
        default=None, description="Optional RNG seed for a reproducible projection."
    )
    # None = FULL nav_timeseries/eod history (the builder/backtest convention).
    # An explicit int (30..3650 days) narrows the estimation window.
    window_days: Annotated[int | None, Field(ge=30, le=3650)] = None

    @field_validator("horizons")
    @classmethod
    def _check_horizons(cls, value: list[int] | None) -> list[int] | None:
        if value is None:
            return None
        if len(value) == 0:
            raise ValueError("horizons must be non-empty when supplied")
        if any(h < 1 for h in value):
            raise ValueError("horizons must all be >= 1 trading day")
        return value


class PortfolioMonteCarloParams(BaseModel):
    """Echo of the resolved portfolio MC parameters (no ticker; n_assets instead)."""

    statistic: Statistic
    n_assets: int
    n_simulations: int
    risk_free_rate: float
    seed: int | None = Field(description="Seed used, or null when unseeded.")


class PortfolioMonteCarloResponse(BaseModel):
    """Render-ready portfolio Monte Carlo payload.

    Reuses the single-instrument distribution shape (``ConfidenceBar``,
    percentiles, historical rank, degraded flags); only ``params`` differs
    (n_assets instead of ticker/range). Drawdown/return fields are decimal
    fractions (0.05 = 5%); sharpe is unitless.
    """

    params: PortfolioMonteCarloParams
    percentiles: dict[str, float] = Field(
        description="Distribution of the statistic at the longest horizon, keyed by "
        "percentile ('1st'..'99th')."
    )
    mean: float
    median: float
    std: float
    historical_value: float = Field(
        description="The statistic computed on the ACTUAL synthetic portfolio series."
    )
    historical_horizon_days: int = Field(
        description="Length of the synthetic portfolio series in trading days."
    )
    historical_percentile_rank: float | None = Field(
        description="Percentile rank (0-100) of the historical value within a "
        "horizon-matched bootstrap; null for the sharpe statistic."
    )
    confidence_bars: list[ConfidenceBar] = Field(
        description="Per-horizon percentile fans (the projection chart)."
    )
    degraded: bool = Field(
        description="True only when a flat-NAV Sharpe collapse made the result uninformative."
    )
    degraded_reason: str | None = Field(
        description="Diagnostic when degraded is True, else null."
    )
