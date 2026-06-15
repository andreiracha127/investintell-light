"""Tests for app.analytics.rolling."""

import numpy as np
import pandas as pd
import pytest

from app.analytics import (
    annualized_volatility,
    beta,
    correlation,
    rolling_annualized_return,
    rolling_beta,
    rolling_correlation,
    rolling_volatility,
)

WINDOW = 10


def _random_returns(n: int = 60, seed: int = 11) -> pd.Series:
    rng = np.random.default_rng(seed)
    return pd.Series(
        rng.normal(0.0004, 0.011, n),
        index=pd.date_range("2024-01-01", periods=n, freq="B"),
    )


def test_rolling_volatility_leading_nans_and_cross_check() -> None:
    """First window-1 values are NaN; value at index window-1 equals the
    scalar function applied to the first window slice."""
    returns = _random_returns()
    result = rolling_volatility(returns, window=WINDOW)
    assert len(result) == len(returns)
    assert result.index.equals(returns.index)
    assert result.iloc[: WINDOW - 1].isna().all()
    expected = annualized_volatility(returns.iloc[:WINDOW])
    assert result.iloc[WINDOW - 1] == pytest.approx(expected, abs=1e-12)
    assert not result.iloc[WINDOW - 1 :].isna().any()


def test_rolling_beta_leading_nans_and_cross_check() -> None:
    asset = _random_returns(seed=11)
    bench = _random_returns(seed=12)
    result = rolling_beta(asset, bench, window=WINDOW)
    assert result.iloc[: WINDOW - 1].isna().all()
    expected = beta(asset.iloc[:WINDOW], bench.iloc[:WINDOW])
    assert result.iloc[WINDOW - 1] == pytest.approx(expected, abs=1e-12)


def test_rolling_beta_zero_variance_window_is_nan() -> None:
    """A window with zero benchmark variance yields NaN (undefined window),
    never a division error or +/-inf."""
    n = 30
    idx = pd.date_range("2024-01-01", periods=n, freq="B")
    asset = pd.Series(np.random.default_rng(5).normal(0, 0.01, n), index=idx)
    bench_values = [0.01] * WINDOW + list(
        np.random.default_rng(6).normal(0, 0.01, n - WINDOW)
    )
    bench = pd.Series(bench_values, index=idx)
    result = rolling_beta(asset, bench, window=WINDOW)
    assert np.isnan(result.iloc[WINDOW - 1])
    assert not np.isinf(result.dropna()).any()


def test_rolling_correlation_leading_nans_and_cross_check() -> None:
    asset = _random_returns(seed=21)
    bench = _random_returns(seed=22)
    result = rolling_correlation(asset, bench, window=WINDOW)
    assert result.iloc[: WINDOW - 1].isna().all()
    expected = correlation(asset.iloc[:WINDOW], bench.iloc[:WINDOW])
    assert result.iloc[WINDOW - 1] == pytest.approx(expected, abs=1e-12)


def test_rolling_aligns_misaligned_series() -> None:
    asset = _random_returns(60, seed=31)
    bench = _random_returns(70, seed=32).iloc[5:]  # overlap = 55 points
    result = rolling_beta(asset, bench, window=WINDOW)
    assert len(result) == 55


def test_rolling_window_too_small_raises() -> None:
    returns = _random_returns()
    with pytest.raises(ValueError, match="window >= 2"):
        rolling_volatility(returns, window=1)
    with pytest.raises(ValueError, match="window >= 2"):
        rolling_beta(returns, returns, window=1)
    with pytest.raises(ValueError, match="window >= 2"):
        rolling_correlation(returns, returns, window=1)


def test_rolling_input_shorter_than_window_raises() -> None:
    returns = _random_returns(5)
    with pytest.raises(ValueError, match="at least window"):
        rolling_volatility(returns, window=WINDOW)
    with pytest.raises(ValueError, match="at least window"):
        rolling_beta(returns, returns, window=WINDOW)
    with pytest.raises(ValueError, match="at least window"):
        rolling_correlation(returns, returns, window=WINDOW)


def test_rolling_annualized_return_leading_nans_and_value() -> None:
    """First window-1 values are NaN; the value at index window-1 equals the
    annualized compounding of the first window slice: (prod(1+r))**(252/w)-1."""
    returns = _random_returns()
    result = rolling_annualized_return(returns, window=WINDOW)
    assert len(result) == len(returns)
    assert result.index.equals(returns.index)
    assert result.iloc[: WINDOW - 1].isna().all()
    first = returns.iloc[:WINDOW]
    expected = float((1.0 + first).prod()) ** (252 / WINDOW) - 1.0
    assert result.iloc[WINDOW - 1] == pytest.approx(expected, abs=1e-12)
    assert not result.iloc[WINDOW - 1 :].isna().any()


def test_rolling_annualized_return_periods_per_year_param() -> None:
    """A non-default periods_per_year changes the annualization exponent."""
    returns = _random_returns()
    result = rolling_annualized_return(returns, window=WINDOW, periods_per_year=12)
    first = returns.iloc[:WINDOW]
    expected = float((1.0 + first).prod()) ** (12 / WINDOW) - 1.0
    assert result.iloc[WINDOW - 1] == pytest.approx(expected, abs=1e-12)


def test_rolling_annualized_return_window_too_small_raises() -> None:
    returns = _random_returns()
    with pytest.raises(ValueError, match="window >= 2"):
        rolling_annualized_return(returns, window=1)


def test_rolling_annualized_return_input_shorter_than_window_raises() -> None:
    returns = _random_returns(5)
    with pytest.raises(ValueError, match="at least window"):
        rolling_annualized_return(returns, window=WINDOW)
