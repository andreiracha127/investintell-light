"""Pure walk-forward / out-of-sample backtest (Tier 2).

Ports ``quant_engine/backtest_service.py`` into the Light analytics layer and
upgrades it to PER-FOLD RE-OPTIMIZATION with cost/turnover accounting (the
model in ``_gate_vs_full_backtest.py``): for each expanding ``TimeSeriesSplit``
fold we (1) solve the objective on the TRAIN window, (2) hold those weights
OUT-OF-SAMPLE over the TEST window, (3) charge a one-way transaction cost on
the L1 weight change vs the previous fold's weights (on the first OOS day), and
(4) score the realized test series with the SAME F3 estimators the rest of the
app uses (``historical_cvar``, ``max_drawdown``) for gate-G3 comparability.

Pure computation — no I/O, no DB, no FastAPI. Fail-loud: ``ValueError`` on
insufficient or NaN data (never NaN out). Scale contract: every fractional
quantity (returns, Sharpe inputs, CVaR, drawdown, turnover) is a decimal
fraction (0.05 = 5%), never 0-100.

Design defaults (from the legacy service docstring):
- ``gap=2``: daily-dealing liquid funds (T+1 NAV + 1 buffer day).
- ``test_size=63``: fixed 3-month OOS windows for comparable per-fold Sharpe.
- expanding window (TimeSeriesSplit default): covariance stability over rolling.
- report fold consistency (positive_folds), not p-values (Finucane 2004).
"""

import datetime as dt
import math
from collections.abc import Callable
from dataclasses import dataclass

import numpy as np
import pandas as pd

from app.analytics.risk import historical_cvar, max_drawdown

TRADING_DAYS = 252

DEFAULT_N_SPLITS = 5
DEFAULT_GAP = 2
DEFAULT_TEST_SIZE = 63
DEFAULT_MIN_TRAIN_SIZE = 252
DEFAULT_CVAR_CONFIDENCE = 0.95
DEFAULT_COST_BPS = 10.0

# A solve function maps a TRAIN return matrix (T_train x n) to long-only,
# sum-to-1 weights (n,). Injected by the caller so the pure loop never imports
# the optimizer (keeps this module dependency-light and unit-testable).
SolveFn = Callable[[np.ndarray], np.ndarray]


@dataclass(frozen=True)
class FoldMetrics:
    """OOS metrics for one walk-forward fold.

    ``sharpe`` annualized; ``cvar_95`` POSITIVE fraction (F3 sign convention);
    ``max_drawdown`` NEGATIVE fraction; ``turnover`` is the L1 weight change vs
    the previous fold (0..2); ``gross_return``/``net_return`` are the fold's
    cumulative OOS returns before/after the one-way transaction cost.
    """

    fold: int
    train_size: int
    n_obs: int
    sharpe: float
    cvar_95: float
    max_drawdown: float
    turnover: float
    gross_return: float
    net_return: float


@dataclass(frozen=True)
class WalkForwardResult:
    folds: list[FoldMetrics]
    n_splits_computed: int
    mean_sharpe: float
    std_sharpe: float
    positive_folds: int
    mean_turnover: float
    cost_bps: float
    # Chained out-of-sample NAV: one (date, nav) point per OOS observation,
    # concatenated across folds in time order. nav starts from the first fold's
    # first OOS day and compounds the per-fold NET daily returns (so the
    # rebalancing cost charged on each fold's first OOS day is already in it).
    oos_curve: list[tuple[dt.date, float]]
    # First OOS date of each fold (the re-optimization / rebalancing points),
    # for the frontend's plotLines.
    fold_boundaries: list[dt.date]


def _annualized_sharpe(returns: np.ndarray, risk_free_daily: float) -> float:
    """Annualized Sharpe of a daily OOS series (mean-excess / std x sqrt(252))."""
    std = float(np.std(returns, ddof=1))
    if std <= 0:
        raise ValueError("fold Sharpe undefined: zero-variance out-of-sample returns")
    mean = float(np.mean(returns))
    return (mean - risk_free_daily) / std * math.sqrt(TRADING_DAYS)


def assemble_walk_forward_backtest(
    returns: pd.DataFrame,
    solve_fn: SolveFn,
    *,
    perf_returns: pd.DataFrame | None = None,
    n_splits: int = DEFAULT_N_SPLITS,
    gap: int = DEFAULT_GAP,
    test_size: int = DEFAULT_TEST_SIZE,
    min_train_size: int = DEFAULT_MIN_TRAIN_SIZE,
    cvar_confidence: float = DEFAULT_CVAR_CONFIDENCE,
    cost_bps: float = DEFAULT_COST_BPS,
    risk_free_annual: float = 0.0,
) -> WalkForwardResult:
    """Walk-forward OOS backtest with per-fold re-optimization.

    Args:
        returns: T x n aligned daily-return frame (rows = dates, cols = assets).
        solve_fn: maps a train return matrix to long-only sum-1 weights.
        n_splits / gap / test_size / min_train_size: TimeSeriesSplit knobs.
        cvar_confidence: tail level for the per-fold CVaR (default 0.95).
        cost_bps: one-way transaction cost in basis points charged on the L1
            weight change vs the previous fold, on the first OOS day.
        risk_free_annual: annual risk-free rate for the Sharpe excess (default
            0.0 — the project's mean/std convention).

    Returns:
        WalkForwardResult with per-fold metrics and the consistency aggregates.

    Raises:
        ValueError: NaN/non-finite returns, fewer than 2 assets, a window too
            short for even one qualifying fold, or a zero-variance fold.
    """
    from sklearn.model_selection import TimeSeriesSplit

    if returns.shape[1] < 2:
        raise ValueError("walk-forward backtest requires at least 2 assets")
    matrix = returns.to_numpy(dtype=float)
    if not np.isfinite(matrix).all():
        raise ValueError("returns contain NaN/inf — refusing to backtest")
    # Dual representation (Bug 1): solve on ``returns`` (LOG → covariance is
    # standard in log) but compose the OOS curve on ``perf_returns`` (SIMPLE).
    # A weighted sum of asset returns is the portfolio return only for SIMPLE
    # returns; composing log as simple is wrong. perf_returns defaults to
    # ``returns`` (back-compatible) and must be index/column aligned.
    if perf_returns is None:
        perf_matrix = matrix
    else:
        if not perf_returns.index.equals(returns.index) or list(
            perf_returns.columns
        ) != list(returns.columns):
            raise ValueError(
                "perf_returns must be index- and column-aligned to returns"
            )
        perf_matrix = perf_returns.to_numpy(dtype=float)
        if not np.isfinite(perf_matrix).all():
            raise ValueError("perf_returns contain NaN/inf — refusing to backtest")
    if not 0 < cvar_confidence < 1:
        raise ValueError(f"cvar_confidence must be in (0, 1), got {cvar_confidence}")
    if cost_bps < 0:
        raise ValueError(f"cost_bps must be >= 0, got {cost_bps}")
    if test_size < 2:
        raise ValueError(f"test_size must be >= 2, got {test_size}")

    t = matrix.shape[0]
    # TimeSeriesSplit needs n_splits*test_size of trailing rows plus room for a
    # min_train_size first-fold train window; this pre-check fires our own
    # message before sklearn raises its generic 'Too many splits' error.
    if t < min_train_size + n_splits * test_size:
        raise ValueError(
            f"insufficient history: {t} observations cannot support {n_splits} folds of "
            f"test_size={test_size} after a {min_train_size}-day minimum train window — "
            "lower n_splits/test_size or supply more history"
        )

    risk_free_daily = risk_free_annual / TRADING_DAYS
    one_way_cost = cost_bps / 1e4
    index = returns.index

    tscv = TimeSeriesSplit(n_splits=n_splits, gap=gap, test_size=test_size)
    folds: list[FoldMetrics] = []
    net_segments: list[pd.Series] = []
    fold_boundaries: list[dt.date] = []
    w_prev = np.zeros(matrix.shape[1])
    for fold_idx, (train_idx, test_idx) in enumerate(tscv.split(matrix)):
        if len(train_idx) < min_train_size:
            continue
        weights = np.asarray(solve_fn(matrix[train_idx]), dtype=float).ravel()
        turnover = float(np.abs(weights - w_prev).sum())

        # Solve uses the LOG train block (above); the OOS holding period composes
        # the SIMPLE perf block so prod(1+r) is a true portfolio return.
        test_block = perf_matrix[test_idx]
        gross_daily = test_block @ weights
        # Charge the one-way cost on the first OOS day (research-script model:
        # _gate_vs_full_backtest.py:123 sr[0] -= turn * COST_BPS / 1e4).
        net_daily = gross_daily.copy()
        net_daily[0] -= turnover * one_way_cost

        oos_index = index[test_idx]
        net_series = pd.Series(net_daily, index=oos_index)
        net_segments.append(net_series)
        fold_boundaries.append(oos_index[0])
        nav = (1.0 + net_series).cumprod()

        sharpe = _annualized_sharpe(net_daily, risk_free_daily)
        cvar_95 = historical_cvar(net_series, confidence=cvar_confidence)
        max_dd = max_drawdown(nav).depth
        gross_return = float(np.prod(1.0 + gross_daily) - 1.0)
        net_return = float(np.prod(1.0 + net_daily) - 1.0)

        folds.append(
            FoldMetrics(
                fold=fold_idx,
                train_size=len(train_idx),
                n_obs=len(test_idx),
                sharpe=round(sharpe, 6),
                cvar_95=round(cvar_95, 6),
                max_drawdown=round(max_dd, 6),
                turnover=round(turnover, 6),
                gross_return=round(gross_return, 6),
                net_return=round(net_return, 6),
            )
        )
        w_prev = weights

    if not folds:
        raise ValueError(
            "no fold cleared the minimum train window — lower min_train_size or "
            "supply more history"
        )

    sharpes = [f.sharpe for f in folds]
    mean_sharpe = float(np.mean(sharpes))
    std_sharpe = float(np.std(sharpes, ddof=1)) if len(sharpes) > 1 else 0.0
    positive_folds = sum(1 for s in sharpes if s > 0)
    mean_turnover = float(np.mean([f.turnover for f in folds]))

    # Chain every fold's NET daily series in time order, then compound once into
    # a single global NAV. Concatenation preserves the per-fold first-day cost
    # already baked into each segment; the result is the realized OOS equity
    # curve of the walk-forward process.
    chained_net = pd.concat(net_segments)
    chained_nav = (1.0 + chained_net).cumprod()
    oos_curve = [
        (idx_date, round(float(value), 8))
        for idx_date, value in zip(chained_nav.index, chained_nav.to_numpy(), strict=True)
    ]

    return WalkForwardResult(
        folds=folds,
        n_splits_computed=len(folds),
        mean_sharpe=round(mean_sharpe, 6),
        std_sharpe=round(std_sharpe, 6),
        positive_folds=positive_folds,
        mean_turnover=round(mean_turnover, 6),
        cost_bps=cost_bps,
        oos_curve=oos_curve,
        fold_boundaries=fold_boundaries,
    )
