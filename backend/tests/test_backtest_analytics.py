"""Pure walk-forward backtest: fold loop + OOS per-fold metrics.

The optimizer is injected as ``solve_fn`` so these tests exercise ONLY the
TimeSeriesSplit fold loop, the out-of-sample holding logic, the cost/turnover
accounting, and the metric aggregation — on deterministic synthetic returns.
"""

import numpy as np
import pandas as pd
import pytest

from app.analytics.backtest import FoldMetrics, WalkForwardResult, assemble_walk_forward_backtest


def _equal_weight_solver(train: np.ndarray) -> np.ndarray:
    """A mu-free, deterministic solve_fn: 1/n regardless of the train window."""
    n = train.shape[1]
    return np.full(n, 1.0 / n)


def _synthetic_returns(n_obs: int = 600, n_assets: int = 3, seed: int = 7) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    index = pd.bdate_range("2018-01-02", periods=n_obs)
    data = {
        f"fund:{i}": rng.normal(0.0004, 0.009 + 0.001 * i, n_obs) for i in range(n_assets)
    }
    return pd.DataFrame(data, index=index)


def test_fold_count_and_shapes_match_timeseriessplit() -> None:
    frame = _synthetic_returns()
    result = assemble_walk_forward_backtest(
        frame, _equal_weight_solver, n_splits=5, gap=2, test_size=63, min_train_size=252
    )
    assert isinstance(result, WalkForwardResult)
    # 5 folds requested; all clear the 252 min_train_size on 600 obs.
    assert result.n_splits_computed == 5
    assert len(result.folds) == 5
    for fold in result.folds:
        assert isinstance(fold, FoldMetrics)
        assert fold.n_obs == 63  # fixed test_size
        assert fold.train_size >= 252


def test_oos_metrics_use_test_window_and_match_engine_estimators() -> None:
    # The LAST fold's test window is exactly the final 63 rows; reconstruct the
    # equal-weight OOS series by hand and confirm the stored CVaR/maxDD equal
    # the live F3 engine on that series. cost_bps=0.0 => net == gross, so the
    # equality holds regardless of turnover.
    from app.analytics import historical_cvar, max_drawdown

    frame = _synthetic_returns()
    result = assemble_walk_forward_backtest(
        frame, _equal_weight_solver, n_splits=5, gap=2, test_size=63,
        min_train_size=252, cost_bps=0.0,
    )
    last = result.folds[-1]
    test_block = frame.iloc[-63:]
    oos_daily = pd.Series(test_block.to_numpy() @ np.full(3, 1.0 / 3), index=test_block.index)
    expected_cvar = historical_cvar(oos_daily, confidence=0.95)
    nav = (1.0 + oos_daily).cumprod()
    expected_dd = max_drawdown(nav).depth  # negative fraction
    assert last.cvar_95 == pytest.approx(round(expected_cvar, 6), abs=1e-9)
    assert last.max_drawdown == pytest.approx(round(expected_dd, 6), abs=1e-9)


def test_positive_folds_and_aggregates() -> None:
    frame = _synthetic_returns(seed=1)
    result = assemble_walk_forward_backtest(
        frame, _equal_weight_solver, n_splits=5, gap=2, test_size=63, min_train_size=252
    )
    sharpes = [f.sharpe for f in result.folds]
    assert result.positive_folds == sum(1 for s in sharpes if s > 0)
    assert result.mean_sharpe == pytest.approx(round(float(np.mean(sharpes)), 6), abs=1e-9)
    assert result.std_sharpe == pytest.approx(round(float(np.std(sharpes, ddof=1)), 6), abs=1e-9)


def test_costs_reduce_realized_return_vs_zero_cost() -> None:
    frame = _synthetic_returns(seed=3)
    gross = assemble_walk_forward_backtest(
        frame, _equal_weight_solver, n_splits=5, gap=2, test_size=63,
        min_train_size=252, cost_bps=0.0,
    )
    net = assemble_walk_forward_backtest(
        frame, _equal_weight_solver, n_splits=5, gap=2, test_size=63,
        min_train_size=252, cost_bps=50.0,
    )
    # Equal-weight re-solve is constant => turnover is 0 only AFTER the first
    # fold; the first fold buys in from cash (turnover==1.0) so cost bites it.
    assert net.folds[0].turnover == pytest.approx(1.0, abs=1e-9)
    assert net.folds[0].net_return < gross.folds[0].net_return
    # No turnover on later folds (weights identical) => identical net return.
    assert net.folds[-1].turnover == pytest.approx(0.0, abs=1e-9)
    assert net.folds[-1].net_return == pytest.approx(gross.folds[-1].net_return, abs=1e-12)


def test_nan_in_returns_is_fail_loud() -> None:
    frame = _synthetic_returns()
    frame.iloc[10, 0] = np.nan
    with pytest.raises(ValueError, match="NaN"):
        assemble_walk_forward_backtest(frame, _equal_weight_solver)


def test_too_few_observations_is_fail_loud() -> None:
    frame = _synthetic_returns(n_obs=120)  # < min_train_size + n_splits*test_size
    with pytest.raises(ValueError, match="insufficient history"):
        assemble_walk_forward_backtest(
            frame, _equal_weight_solver, n_splits=5, gap=2, test_size=63, min_train_size=252
        )


def test_oos_curve_chains_folds_in_time_order() -> None:
    # cost_bps=0 so the chained growth factor equals the product of per-fold
    # (1 + net_return) exactly (no first-day cost perturbing the chain).
    frame = _synthetic_returns(seed=11)
    result = assemble_walk_forward_backtest(
        frame,
        _equal_weight_solver,
        n_splits=5,
        gap=2,
        test_size=63,
        min_train_size=252,
        cost_bps=0.0,
    )
    # One point per OOS observation across all folds.
    assert len(result.oos_curve) == sum(f.n_obs for f in result.folds)
    # Dates strictly increasing in time.
    dates = [d for d, _ in result.oos_curve]
    assert all(earlier < later for earlier, later in zip(dates, dates[1:], strict=False))
    # Final chained growth factor == product of per-fold (1 + net_return).
    final_nav = result.oos_curve[-1][1]
    expected = float(np.prod([1.0 + f.net_return for f in result.folds]))
    assert final_nav == pytest.approx(expected, rel=1e-4)
    # First curve date == start of the first test fold (the final 63*5 window's
    # first test block start). It must equal the first OOS date the loop saw.
    first_date = result.oos_curve[0][0]
    assert first_date == dates[0]
    # fold_boundaries: one per fold, each the first date of that fold's OOS block.
    assert len(result.fold_boundaries) == len(result.folds)
    assert result.fold_boundaries[0] == first_date
    assert all(b in set(dates) for b in result.fold_boundaries)


def test_oos_curve_values_are_finite_and_positive() -> None:
    frame = _synthetic_returns(seed=12)
    result = assemble_walk_forward_backtest(
        frame,
        _equal_weight_solver,
        n_splits=5,
        gap=2,
        test_size=63,
        min_train_size=252,
    )
    navs = [v for _, v in result.oos_curve]
    assert all(np.isfinite(v) and v > 0 for v in navs)
