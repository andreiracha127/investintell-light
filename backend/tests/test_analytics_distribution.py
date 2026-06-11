"""Tests for app.analytics.distribution."""

import numpy as np
import pandas as pd
import pytest

from app.analytics import return_histogram


def _random_returns(n: int = 100, seed: int = 9) -> pd.Series:
    rng = np.random.default_rng(seed)
    return pd.Series(
        rng.normal(0.0, 0.01, n),
        index=pd.date_range("2024-01-01", periods=n, freq="B"),
    )


def test_histogram_counts_sum_to_number_of_returns() -> None:
    returns = _random_returns()
    hist = return_histogram(returns, bins=20)
    assert sum(hist.counts) == len(returns)


def test_histogram_normalized_max_is_one() -> None:
    hist = return_histogram(_random_returns(), bins=20)
    assert max(hist.counts_normalized) == 1.0
    assert all(0.0 <= v <= 1.0 for v in hist.counts_normalized)


def test_histogram_shapes() -> None:
    hist = return_histogram(_random_returns(), bins=15)
    assert len(hist.counts) == 15
    assert len(hist.bin_edges) == 16
    assert len(hist.counts_normalized) == 15
    assert hist.bin_edges == sorted(hist.bin_edges)


def test_histogram_short_input_raises() -> None:
    with pytest.raises(ValueError, match="at least 10"):
        return_histogram(_random_returns(9))


def test_histogram_bins_out_of_bounds_raises() -> None:
    returns = _random_returns()
    with pytest.raises(ValueError, match="bins"):
        return_histogram(returns, bins=0)
    with pytest.raises(ValueError, match="bins"):
        return_histogram(returns, bins=101)


def test_histogram_nan_input_raises() -> None:
    returns = _random_returns()
    returns.iloc[3] = np.nan
    with pytest.raises(ValueError, match="NaN"):
        return_histogram(returns)
