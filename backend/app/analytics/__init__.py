"""Quant analytics engine: single-asset (F2) and static portfolio (F3).

Pure functions over pandas/numpy — no database access, no I/O, no FastAPI.
Scale contract (project-wide): all fractional quantities (returns, vol,
VaR, CVaR, drawdown) are decimal fractions (0.05 = 5%), never 0-100.
"""

from app.analytics.absorption import AbsorptionResult, absorption_ratio
from app.analytics.active_share import active_share
from app.analytics.distribution import Histogram, return_histogram
from app.analytics.portfolio import (
    DEFAULT_INITIAL_NAV,
    asset_returns_frame,
    correlation_matrix,
    diversification_ratio,
    effective_number_of_bets,
    enb_from_contributions,
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
    to_monthly_returns,
    total_return,
)
from app.analytics.risk import (
    _MIN_TAIL_POINTS as MIN_IN_RANGE_RETURNS,
)
from app.analytics.risk import (
    DEFAULT_RISK_FREE_RATE,
    BestWorst,
    DrawdownEpisode,
    DrawdownResult,
    annualized_volatility,
    best_worst_day,
    beta,
    correlation,
    drawdown_episodes,
    historical_cvar,
    historical_var,
    information_ratio,
    max_drawdown,
    realized_cvar,
    sharpe_ratio,
    sortino_ratio,
)
from app.analytics.risk_budgeting import (
    EtlRiskBudget,
    VarianceRiskBudget,
    etl_implied_returns,
    etl_risk_budget,
    portfolio_starr,
    sharpe_implied_returns,
    variance_risk_budget,
)
from app.analytics.robust_sharpe import (
    RobustSharpeResult,
    robust_sharpe,
)
from app.analytics.rolling import (
    rolling_annualized_return,
    rolling_beta,
    rolling_correlation,
    rolling_volatility,
)

__all__ = [
    "AbsorptionResult",
    "BestWorst",
    "DEFAULT_INITIAL_NAV",
    "DEFAULT_RISK_FREE_RATE",
    "DrawdownEpisode",
    "DrawdownResult",
    "EtlRiskBudget",
    "Histogram",
    "MIN_IN_RANGE_RETURNS",
    "RobustSharpeResult",
    "VarianceRiskBudget",
    "absorption_ratio",
    "active_share",
    "align_returns",
    "annualized_volatility",
    "asset_returns_frame",
    "best_worst_day",
    "beta",
    "correlation",
    "correlation_matrix",
    "cumulative_return_series",
    "diversification_ratio",
    "drawdown_episodes",
    "effective_number_of_bets",
    "enb_from_contributions",
    "etl_implied_returns",
    "etl_risk_budget",
    "historical_cvar",
    "historical_var",
    "information_ratio",
    "max_drawdown",
    "nav_by_position",
    "portfolio_nav",
    "portfolio_returns",
    "portfolio_starr",
    "realized_cvar",
    "return_histogram",
    "risk_contributions",
    "robust_sharpe",
    "rolling_annualized_return",
    "rolling_beta",
    "rolling_correlation",
    "rolling_volatility",
    "sharpe_implied_returns",
    "sharpe_ratio",
    "simple_returns",
    "sortino_ratio",
    "to_monthly_returns",
    "total_return",
    "variance_risk_budget",
    "weight_series",
    "weights_to_quantities",
]
