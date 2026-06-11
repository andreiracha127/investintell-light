"""Single-asset quant analytics engine.

Pure functions over pandas/numpy — no database access, no I/O, no FastAPI.
Scale contract (project-wide): all fractional quantities (returns, vol,
VaR, CVaR, drawdown) are decimal fractions (0.05 = 5%), never 0-100.
"""

from app.analytics.distribution import Histogram, return_histogram
from app.analytics.returns import (
    align_returns,
    cumulative_return_series,
    simple_returns,
    total_return,
)
from app.analytics.risk import (
    _MIN_TAIL_POINTS as MIN_IN_RANGE_RETURNS,
)
from app.analytics.risk import (
    BestWorst,
    DrawdownResult,
    annualized_volatility,
    best_worst_day,
    beta,
    correlation,
    historical_cvar,
    historical_var,
    max_drawdown,
)
from app.analytics.rolling import (
    rolling_beta,
    rolling_correlation,
    rolling_volatility,
)

__all__ = [
    "BestWorst",
    "DrawdownResult",
    "Histogram",
    "MIN_IN_RANGE_RETURNS",
    "align_returns",
    "annualized_volatility",
    "best_worst_day",
    "beta",
    "correlation",
    "cumulative_return_series",
    "historical_cvar",
    "historical_var",
    "max_drawdown",
    "return_histogram",
    "rolling_beta",
    "rolling_correlation",
    "rolling_volatility",
    "simple_returns",
    "total_return",
]
