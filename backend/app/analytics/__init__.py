"""Quant analytics engine: single-asset (F2) and static portfolio (F3).

Pure functions over pandas/numpy — no database access, no I/O, no FastAPI.
Scale contract (project-wide): all fractional quantities (returns, vol,
VaR, CVaR, drawdown) are decimal fractions (0.05 = 5%), never 0-100.
"""

from app.analytics.distribution import Histogram, return_histogram
from app.analytics.portfolio import (
    DEFAULT_INITIAL_NAV,
    asset_returns_frame,
    correlation_matrix,
    diversification_ratio,
    effective_number_of_bets,
    nav_by_position,
    portfolio_nav,
    portfolio_returns,
    risk_contributions,
    weight_series,
    weights_to_quantities,
)
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
    DEFAULT_RISK_FREE_RATE,
    BestWorst,
    DrawdownResult,
    annualized_volatility,
    best_worst_day,
    beta,
    correlation,
    historical_cvar,
    historical_var,
    information_ratio,
    max_drawdown,
    realized_cvar,
    sharpe_ratio,
    sortino_ratio,
)
from app.analytics.rolling import (
    rolling_beta,
    rolling_correlation,
    rolling_volatility,
)

__all__ = [
    "BestWorst",
    "DEFAULT_INITIAL_NAV",
    "DEFAULT_RISK_FREE_RATE",
    "DrawdownResult",
    "Histogram",
    "MIN_IN_RANGE_RETURNS",
    "align_returns",
    "annualized_volatility",
    "asset_returns_frame",
    "best_worst_day",
    "beta",
    "correlation",
    "correlation_matrix",
    "cumulative_return_series",
    "diversification_ratio",
    "effective_number_of_bets",
    "historical_cvar",
    "historical_var",
    "information_ratio",
    "max_drawdown",
    "nav_by_position",
    "portfolio_nav",
    "portfolio_returns",
    "realized_cvar",
    "return_histogram",
    "risk_contributions",
    "sharpe_ratio",
    "rolling_beta",
    "rolling_correlation",
    "rolling_volatility",
    "simple_returns",
    "sortino_ratio",
    "total_return",
    "weight_series",
    "weights_to_quantities",
]
