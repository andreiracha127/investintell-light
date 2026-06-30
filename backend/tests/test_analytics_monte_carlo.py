"""Tests for app.analytics.monte_carlo (block-bootstrap Monte Carlo)."""

import numpy as np
import pytest

from app.analytics.monte_carlo import (
    DEFAULT_HORIZONS,
    MonteCarloAnalytics,
    block_bootstrap_monte_carlo,
)


def _returns(n: int = 500, seed: int = 11) -> np.ndarray:
    """Deterministic daily returns with positive drift and ~1% daily vol."""
    rng = np.random.default_rng(seed)
    return rng.normal(0.0004, 0.01, n)


def test_max_drawdown_distribution_is_deterministic_under_seed() -> None:
    r = _returns()
    a = block_bootstrap_monte_carlo(r, n_simulations=2000, statistic="max_drawdown", seed=42)
    b = block_bootstrap_monte_carlo(r, n_simulations=2000, statistic="max_drawdown", seed=42)
    assert a == b  # frozen dataclass equality => bit-for-bit reproducible


def test_max_drawdown_result_shape_and_ordering() -> None:
    r = _returns()
    res = block_bootstrap_monte_carlo(r, n_simulations=2000, statistic="max_drawdown", seed=1)
    assert isinstance(res, MonteCarloAnalytics)
    assert res.statistic == "max_drawdown"
    assert res.n_simulations == 2000
    assert not res.degraded
    # Percentile keys present and monotone (max drawdown is negative; deeper at low pct).
    keys = ["1st", "5th", "10th", "25th", "50th", "75th", "90th", "95th", "99th"]
    assert list(res.percentiles.keys()) == keys
    vals = [res.percentiles[k] for k in keys]
    assert vals == sorted(vals)  # ascending: 1st (worst, most negative) -> 99th
    # All drawdowns are <= 0 decimal fractions.
    assert res.percentiles["99th"] <= 0.0
    # Confidence fan covers DEFAULT_HORIZONS, each with a 1Y..10Y label.
    assert [b["horizon_days"] for b in res.confidence_bars] == DEFAULT_HORIZONS
    assert res.confidence_bars[0]["horizon"] == "1Y"


def test_historical_percentile_rank_present_for_drawdown() -> None:
    r = _returns()
    res = block_bootstrap_monte_carlo(r, n_simulations=2000, statistic="max_drawdown", seed=3)
    assert res.historical_percentile_rank is not None
    assert 0.0 <= res.historical_percentile_rank <= 100.0
    assert res.historical_horizon_days == len(r)


def test_return_statistic_annualizes() -> None:
    r = _returns()
    res = block_bootstrap_monte_carlo(r, n_simulations=1500, statistic="return", seed=5)
    assert res.statistic == "return"
    # Median annualized return is finite and within a sane band for the inputs.
    assert -1.0 < res.median < 5.0
    assert res.historical_percentile_rank is not None


def test_return_confidence_bars_are_cumulative_and_widen_with_horizon() -> None:
    """The per-horizon fan must widen over time (a "range of outcomes" cone),

    unlike the headline ``median``/``percentiles`` above, which stay annualized
    (CAGR) and therefore narrow with horizon — that's a different, correct
    statistic used for cross-horizon rate comparisons, not for the chart.
    """
    r = _returns(n=1500, seed=11)
    res = block_bootstrap_monte_carlo(r, n_simulations=1500, statistic="return", seed=5)
    widths = [b["pct_95"] - b["pct_5"] for b in res.confidence_bars]
    assert widths == sorted(widths)  # strictly non-decreasing as horizon grows
    assert widths[-1] > widths[0]
    # 1Y cumulative return roughly matches the annualized rate (h ≈ 252 days);
    # by 10Y the two diverge sharply because cumulative compounds the rate.
    one_year, ten_year = res.confidence_bars[0], res.confidence_bars[-1]
    assert one_year["horizon"] == "1Y"
    assert ten_year["horizon"] == "10Y"


def test_sharpe_confidence_bars_still_narrow_with_horizon() -> None:
    """Unlike return, Sharpe has no cumulative analogue and stays annualized

    everywhere — its per-horizon band narrowing is the statistically correct
    behavior (a longer simulated track record makes the risk-adjusted-return
    estimate more reliable), not a bug to "fix".
    """
    r = _returns(n=1500, seed=11)
    res = block_bootstrap_monte_carlo(r, n_simulations=1500, statistic="sharpe", seed=5)
    widths = [b["pct_95"] - b["pct_5"] for b in res.confidence_bars]
    assert widths[-1] < widths[0]


def test_sharpe_statistic_no_rank() -> None:
    r = _returns()
    res = block_bootstrap_monte_carlo(r, n_simulations=1500, statistic="sharpe", seed=7)
    assert res.statistic == "sharpe"
    # Per the legacy contract, the percentile rank is omitted for sharpe.
    assert res.historical_percentile_rank is None
    assert not res.degraded


def test_flat_returns_sharpe_degrades() -> None:
    flat = np.zeros(300)
    res = block_bootstrap_monte_carlo(flat, n_simulations=500, statistic="sharpe", seed=9)
    assert res.degraded is True
    assert res.degraded_reason is not None
    assert "zero_variance" in res.degraded_reason


def test_unknown_statistic_raises() -> None:
    with pytest.raises(ValueError, match="Unknown statistic"):
        block_bootstrap_monte_carlo(_returns(), statistic="median", seed=1)


def test_too_short_history_raises() -> None:
    with pytest.raises(ValueError, match="insufficient_history"):
        block_bootstrap_monte_carlo(_returns(n=40), statistic="max_drawdown", seed=1)


def test_horizon_ratio_guard_raises() -> None:
    # 60 days of history but asking for a 10Y (2520-day) horizon: need T >= 252.
    with pytest.raises(ValueError, match="insufficient_history_for_horizon"):
        block_bootstrap_monte_carlo(_returns(n=60), statistic="max_drawdown", seed=1)


def test_custom_horizons_respected() -> None:
    r = _returns()
    res = block_bootstrap_monte_carlo(
        r, n_simulations=1000, statistic="max_drawdown", horizons=[252, 504], seed=2
    )
    assert [b["horizon_days"] for b in res.confidence_bars] == [252, 504]
