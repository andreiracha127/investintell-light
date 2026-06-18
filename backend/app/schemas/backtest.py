"""Schemas for the walk-forward backtest endpoint (Tier 2).

Scale contract (project-wide): weights, returns, Sharpe, CVaR, drawdown and
turnover are decimal fractions (0.05 = 5%), never 0-100. ``cost_bps`` is the
one-way transaction cost in BASIS POINTS (10 = 0.10%). The asset references and
constraints reuse the builder vocabulary so a backtest takes the exact request
a user already built in POST /builder/optimize.
"""

import datetime as dt
from typing import Annotated

from pydantic import BaseModel, Field, model_validator

from app.schemas.analysis import SeriesPoint
from app.schemas.builder import AssetRefIn, ConstraintsIn, Objective

__all__ = [
    "SeriesPoint",
    "WalkForwardRequest",
    "FoldMetricsOut",
    "WalkForwardParams",
    "WalkForwardResponse",
]

# -- Request -------------------------------------------------------------------


class WalkForwardRequest(BaseModel):
    """Walk-forward / OOS backtest over an explicit asset list.

    The objective is RE-OPTIMIZED on each expanding TimeSeriesSplit train fold
    and held out-of-sample over the following test fold. ``min_cvar`` (the
    product default) is mu-free; BL ``views`` are intentionally NOT accepted
    here (a backtest must not peek at user views formed with hindsight) —
    backtests run the mu-free objectives only.
    """

    assets: Annotated[list[AssetRefIn], Field(min_length=2, max_length=50)]
    objective: Objective = "min_cvar"
    constraints: ConstraintsIn = ConstraintsIn()
    # None = FULL nav_timeseries history (the builder's convention). An explicit
    # int (30..3650 days) narrows the loaded window before folding.
    window_days: Annotated[int | None, Field(ge=30, le=3650)] = None
    n_splits: Annotated[int, Field(ge=2, le=20)] = 5
    gap: Annotated[int, Field(ge=0, le=63)] = 2
    test_size: Annotated[int, Field(ge=20, le=504)] = 63
    min_train_size: Annotated[int, Field(ge=60, le=5000)] = 252
    cost_bps: Annotated[float, Field(ge=0, le=1000)] = 10.0
    risk_free_annual: Annotated[float, Field(ge=0, le=1)] = 0.0
    # Daily tail-loss cap for the ``max_return_cvar`` (equilibrium) objective
    # (decimal fraction, e.g. 0.02 = 2% daily CVaR_95). Required for that
    # objective, ignored otherwise. Mirrors OptimizeRequest.cvar_limit.
    cvar_limit: Annotated[float, Field(gt=0, le=1)] | None = None

    @model_validator(mode="after")
    def _check_cvar_limit(self) -> "WalkForwardRequest":
        if self.objective == "max_return_cvar" and self.cvar_limit is None:
            raise ValueError(
                "max_return_cvar requires a cvar_limit (daily tail-loss cap) - "
                "the walk-forward runs the equilibrium objective (pi = delta * Sigma * w_mkt) "
                "with no views"
            )
        return self


# -- Response ------------------------------------------------------------------


class FoldMetricsOut(BaseModel):
    fold: int
    train_size: int
    n_obs: int
    sharpe: float
    # POSITIVE fraction (F3 sign convention): cvar_95=0.02 -> 2% expected tail loss.
    cvar_95: float
    # NEGATIVE fraction: -0.08 -> 8% peak-to-trough OOS drawdown.
    max_drawdown: float
    # L1 weight change vs the previous fold (0..2).
    turnover: float
    gross_return: float
    net_return: float


class WalkForwardParams(BaseModel):
    objective: Objective
    n_obs: int
    n_splits_computed: int
    gap: int
    test_size: int
    min_train_size: int
    cost_bps: float


class WalkForwardResponse(BaseModel):
    folds: list[FoldMetricsOut]
    params: WalkForwardParams
    mean_sharpe: float
    std_sharpe: float
    # Consistency, not significance: how many of n folds had a positive Sharpe.
    positive_folds: int
    mean_turnover: float
    # Realized out-of-sample equity curve: [date, nav] points compounded across
    # folds in time order (nav fraction, starts near 1.0). The fold boundaries
    # are the per-fold first OOS dates (re-optimization / rebalancing points).
    oos_curve: list[SeriesPoint] = Field(
        default_factory=list,
        description="Chained OOS NAV as [date, nav] points (decimal fraction NAV).",
    )
    fold_boundaries: list[dt.date] = Field(
        default_factory=list,
        description="First OOS date of each fold (plotLine markers).",
    )
