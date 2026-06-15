"""Walk-forward backtest service (Tier 2): DB -> aligned returns -> per-fold
re-optimization -> OOS metrics -> response schema.

Pattern (project convention): the pure ``assemble_*`` lives in
``app.analytics.backtest``; this module is the async ``run_*`` orchestrator
(loads from the data-lake, builds the per-objective solve closure, calls the
pure assemble, maps to the schema). The route stays thin.

solve_fn contract: each objective's closure maps a TRAIN return matrix to
long-only sum-1 weights using ONLY ``app.optimizer.engine`` (mu-free). No BL /
views path: a backtest must not consume hindsight views.

Error contract: every domain failure (bad/short history, solver non-optimal,
zero-variance fold) raises ``BacktestError`` -> 422 with the message verbatim.
"""

import numpy as np
import pandas as pd
from sqlalchemy.ext.asyncio import AsyncSession

from app.analytics.backtest import SolveFn, assemble_walk_forward_backtest
from app.optimizer import data as optimizer_data
from app.optimizer import engine
from app.schemas.backtest import (
    FoldMetricsOut,
    WalkForwardParams,
    WalkForwardRequest,
    WalkForwardResponse,
)
from app.schemas.builder import Objective
from app.services.portfolio_builder import _to_data_ref


class BacktestError(ValueError):
    """Domain failure in the backtest — mapped verbatim to HTTP 422."""


def _solve_fn_for(
    objective: Objective, cap: float | None, min_weight: float | None
) -> SolveFn:
    """Build the per-fold solver closure for a mu-free objective.

    Wraps ``app.optimizer.engine`` so each call re-optimizes on the fold's TRAIN
    matrix. ``min_cvar`` solves on the raw scenarios (Rockafellar-Uryasev); the
    covariance objectives shrink Sigma with Ledoit-Wolf first. BL objectives
    (``bl_utility``) are rejected up-front — backtests are mu-free. Each engine
    solver returns a ``(weights, status)`` tuple, so the closure keeps weights.
    """
    if objective == "bl_utility":
        raise BacktestError(
            "bl_utility is not backtestable: Black-Litterman views are formed "
            "with hindsight; backtest a mu-free objective (min_cvar/min_vol/erc/"
            "max_diversification/equal_weight)"
        )

    def solve(train: np.ndarray) -> np.ndarray:
        if objective == "min_cvar":
            weights, _ = engine.solve_min_cvar(train, cap=cap, min_weight=min_weight)
        elif objective == "min_vol":
            sigma = engine.sigma_ledoit_wolf(train)
            weights, _ = engine.solve_min_vol(sigma, cap=cap, min_weight=min_weight)
        elif objective == "erc":
            sigma = engine.sigma_ledoit_wolf(train)
            weights, _ = engine.solve_erc(sigma, cap=cap, min_weight=min_weight)
        elif objective == "max_diversification":
            sigma = engine.sigma_ledoit_wolf(train)
            weights, _ = engine.solve_max_diversification(
                sigma, cap=cap, min_weight=min_weight
            )
        elif objective == "equal_weight":
            weights, _ = engine.solve_equal_weight(
                train.shape[1], cap=cap, min_weight=min_weight
            )
        else:  # pragma: no cover - Objective Literal + bl_utility guard above
            raise BacktestError(f"unknown objective: {objective}")
        return weights

    return solve


async def run_walk_forward_backtest(
    session: AsyncSession, payload: WalkForwardRequest
) -> WalkForwardResponse:
    refs = [_to_data_ref(ref) for ref in payload.assets]
    try:
        frame: pd.DataFrame = await optimizer_data.load_aligned_returns(
            session, refs, window_days=payload.window_days
        )
    except ValueError as exc:
        raise BacktestError(str(exc)) from exc

    solve_fn = _solve_fn_for(
        payload.objective, payload.constraints.cap, payload.constraints.min_weight
    )
    try:
        result = assemble_walk_forward_backtest(
            frame,
            solve_fn,
            n_splits=payload.n_splits,
            gap=payload.gap,
            test_size=payload.test_size,
            min_train_size=payload.min_train_size,
            cost_bps=payload.cost_bps,
            risk_free_annual=payload.risk_free_annual,
        )
    except engine.OptimizerError as exc:
        raise BacktestError(str(exc)) from exc
    except ValueError as exc:
        raise BacktestError(str(exc)) from exc

    return WalkForwardResponse(
        folds=[
            FoldMetricsOut(
                fold=f.fold,
                train_size=f.train_size,
                n_obs=f.n_obs,
                sharpe=f.sharpe,
                cvar_95=f.cvar_95,
                max_drawdown=f.max_drawdown,
                turnover=f.turnover,
                gross_return=f.gross_return,
                net_return=f.net_return,
            )
            for f in result.folds
        ],
        params=WalkForwardParams(
            objective=payload.objective,
            n_obs=len(frame),
            n_splits_computed=result.n_splits_computed,
            gap=payload.gap,
            test_size=payload.test_size,
            min_train_size=payload.min_train_size,
            cost_bps=result.cost_bps,
        ),
        mean_sharpe=result.mean_sharpe,
        std_sharpe=result.std_sharpe,
        positive_folds=result.positive_folds,
        mean_turnover=result.mean_turnover,
    )
