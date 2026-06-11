"""Tests for app.analytics.risk."""

import math

import numpy as np
import pandas as pd
import pytest

from app.analytics import (
    annualized_volatility,
    best_worst_day,
    beta,
    correlation,
    historical_cvar,
    historical_var,
    max_drawdown,
)


def _dated(values: list[float], start: str = "2024-01-01") -> pd.Series:
    return pd.Series(values, index=pd.date_range(start, periods=len(values), freq="B"))


def _random_returns(n: int = 250, seed: int = 7) -> pd.Series:
    rng = np.random.default_rng(seed)
    return _dated(list(rng.normal(0.0003, 0.012, n)))


# --- VaR / CVaR intent tests -------------------------------------------------


def test_var_99_at_least_var_95() -> None:
    """By our positive-loss convention VaR99 >= VaR95.

    A 99% confidence level looks deeper into the loss tail than 95%, and a
    deeper tail quantile is a larger loss. Since we report VaR as a POSITIVE
    loss magnitude, the 99% figure must be >= the 95% figure.
    """
    returns = _random_returns()
    assert historical_var(returns, 0.99) >= historical_var(returns, 0.95)


def test_cvar_at_least_var() -> None:
    """CVaR 95 >= VaR 95: the average loss beyond the quantile is at least
    the quantile itself (expected shortfall dominates the threshold)."""
    returns = _random_returns()
    assert historical_cvar(returns, 0.95) >= historical_var(returns, 0.95)


def test_var_is_positive_for_lossy_series() -> None:
    returns = _random_returns()
    assert historical_var(returns, 0.95) > 0


def test_var_short_input_raises() -> None:
    with pytest.raises(ValueError, match="at least 10"):
        historical_var(_dated([0.01] * 9))


def test_cvar_short_input_raises() -> None:
    with pytest.raises(ValueError, match="at least 10"):
        historical_cvar(_dated([0.01] * 9))


def test_var_bad_confidence_raises() -> None:
    with pytest.raises(ValueError, match="confidence"):
        historical_var(_random_returns(), confidence=95.0)


# --- volatility ---------------------------------------------------------------


def test_annualized_volatility_zero_for_constant_returns() -> None:
    assert annualized_volatility(_dated([0.01] * 30)) == pytest.approx(0.0, abs=1e-12)


def test_annualized_volatility_short_input_raises() -> None:
    with pytest.raises(ValueError, match="at least 2"):
        annualized_volatility(_dated([0.01]))


def test_annualized_volatility_nan_input_raises() -> None:
    with pytest.raises(ValueError, match="NaN"):
        annualized_volatility(_dated([0.01, np.nan, 0.02]))


# --- drawdown -----------------------------------------------------------------


def test_max_drawdown_depth_nonpositive_and_dates_ordered() -> None:
    """Drawdown depth is always <= 0 and the peak precedes the trough."""
    rng = np.random.default_rng(3)
    prices = _dated(list(100 * np.cumprod(1 + rng.normal(0.0002, 0.015, 200))))
    result = max_drawdown(prices)
    assert result.depth <= 0
    assert result.peak_date <= result.trough_date


def test_max_drawdown_known_path() -> None:
    # 100 -> 120 (peak) -> 90 (trough): depth = 90/120 - 1 = -0.25
    prices = _dated([100.0, 120.0, 110.0, 90.0, 95.0])
    result = max_drawdown(prices)
    assert result.depth == pytest.approx(-0.25)
    assert result.peak_date == prices.index[1].date()
    assert result.trough_date == prices.index[3].date()


def test_max_drawdown_monotonic_rise_is_zero() -> None:
    result = max_drawdown(_dated([100.0, 101.0, 102.0, 103.0]))
    assert result.depth == 0.0
    assert result.peak_date <= result.trough_date


def test_max_drawdown_short_input_raises() -> None:
    with pytest.raises(ValueError, match="at least 2"):
        max_drawdown(_dated([100.0]))


def test_max_drawdown_mid_series_nan_raises() -> None:
    """NaN in the middle of the price series must be rejected before cummax/idxmin.

    Without an up-front guard, cummax() and idxmin() skip NaN silently and
    [100, 120, NaN, 90, 95] would return -0.25 instead of raising.
    """
    prices = _dated([100.0, 120.0, float("nan"), 90.0, 95.0])
    with pytest.raises(ValueError, match="NaN"):
        max_drawdown(prices)


# --- best/worst day -----------------------------------------------------------


def test_best_worst_day() -> None:
    returns = _dated([0.01, -0.03, 0.05, -0.01])
    result = best_worst_day(returns)
    assert result.best_return == pytest.approx(0.05)
    assert result.best_date == returns.index[2].date()
    assert result.worst_return == pytest.approx(-0.03)
    assert result.worst_date == returns.index[1].date()


def test_best_worst_day_empty_raises() -> None:
    with pytest.raises(ValueError, match="at least 1"):
        best_worst_day(pd.Series([], dtype=float))


def test_best_worst_day_nan_raises() -> None:
    """NaN in the series must be rejected up-front (idxmax/idxmin skip NaN silently)."""
    returns = _dated([0.01, float("nan"), -0.02])
    with pytest.raises(ValueError, match="NaN"):
        best_worst_day(returns)


# --- beta / correlation -------------------------------------------------------


def test_beta_of_series_against_itself_is_one() -> None:
    returns = _random_returns()
    assert beta(returns, returns) == pytest.approx(1.0, abs=1e-12)


def test_beta_of_scaled_benchmark_is_two() -> None:
    bench = _random_returns()
    assert beta(2 * bench, bench) == pytest.approx(2.0, abs=1e-12)


def test_beta_zero_variance_benchmark_raises() -> None:
    asset = _random_returns(50)
    flat = _dated([0.01] * 50)
    with pytest.raises(ValueError, match="variance"):
        beta(asset, flat)


def test_beta_too_few_common_points_raises() -> None:
    a = _random_returns(5)
    with pytest.raises(ValueError, match="at least 10"):
        beta(a, a)


def test_correlation_identical_is_one() -> None:
    returns = _random_returns()
    assert correlation(returns, returns) == pytest.approx(1.0, abs=1e-12)


def test_correlation_negated_is_minus_one() -> None:
    returns = _random_returns()
    assert correlation(returns, -returns) == pytest.approx(-1.0, abs=1e-12)


def test_correlation_zero_variance_raises() -> None:
    asset = _random_returns(50)
    flat = _dated([0.01] * 50)
    with pytest.raises(ValueError, match="variance"):
        correlation(asset, flat)


def test_correlation_too_few_common_points_raises() -> None:
    a = _random_returns(5)
    with pytest.raises(ValueError, match="at least 10"):
        correlation(a, a)


# --- property tests -----------------------------------------------------------


def test_annualized_volatility_scale_invariance() -> None:
    """vol(r, ppy=k) == vol(r, ppy=1) * sqrt(k) to within floating-point tolerance.

    The annualisation factor is sqrt(ppy), so scaling ppy by k must scale the
    result by sqrt(k) exactly (up to floating-point rounding).
    """
    r = _random_returns(250, seed=42)
    k = 252
    vol_k = annualized_volatility(r, periods_per_year=k)
    vol_1 = annualized_volatility(r, periods_per_year=1)
    assert vol_k == pytest.approx(vol_1 * math.sqrt(k), abs=1e-12)


def test_cvar_monotonicity() -> None:
    """CVaR(99%) >= CVaR(95%) on a seeded return series.

    A higher confidence level looks deeper into the loss tail, so the
    conditional expected loss must be at least as large.
    """
    r = _random_returns(500, seed=17)
    assert historical_cvar(r, 0.99) >= historical_cvar(r, 0.95)
