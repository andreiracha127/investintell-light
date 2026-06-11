"""Tests for app.analytics.returns."""

import numpy as np
import pandas as pd
import pytest

from app.analytics import (
    align_returns,
    cumulative_return_series,
    simple_returns,
    total_return,
)


def _dated(values: list[float], start: str = "2024-01-01") -> pd.Series:
    return pd.Series(values, index=pd.date_range(start, periods=len(values), freq="B"))


def test_simple_returns_values() -> None:
    prices = _dated([100.0, 110.0, 99.0])
    result = simple_returns(prices)
    assert len(result) == 2
    assert result.iloc[0] == pytest.approx(0.10)
    assert result.iloc[1] == pytest.approx(-0.10)
    assert not result.isna().any()


def test_simple_returns_requires_two_points() -> None:
    with pytest.raises(ValueError, match="at least 2"):
        simple_returns(_dated([100.0]))


def test_cumulative_return_series_compounds() -> None:
    returns = _dated([0.10, 0.10])
    result = cumulative_return_series(returns)
    assert result.iloc[0] == pytest.approx(0.10)
    assert result.iloc[1] == pytest.approx(0.21)  # 1.1 * 1.1 - 1


def test_cumulative_return_series_empty_raises() -> None:
    with pytest.raises(ValueError, match="at least 1"):
        cumulative_return_series(pd.Series([], dtype=float))


def test_total_return_matches_cumulative_last() -> None:
    rng = np.random.default_rng(42)
    returns = _dated(list(rng.normal(0.0005, 0.01, 50)))
    assert total_return(returns) == pytest.approx(cumulative_return_series(returns).iloc[-1])


def test_total_return_empty_raises() -> None:
    with pytest.raises(ValueError, match="at least 1"):
        total_return(pd.Series([], dtype=float))


def test_total_return_nan_raises() -> None:
    returns = _dated([0.01, float("nan"), 0.02])
    with pytest.raises(ValueError, match="NaN"):
        total_return(returns)


def test_cumulative_return_series_nan_raises() -> None:
    returns = _dated([0.01, float("nan"), 0.02])
    with pytest.raises(ValueError, match="NaN"):
        cumulative_return_series(returns)


def test_align_returns_drops_non_overlapping_dates() -> None:
    """Misaligned series must be inner-joined: only common dates survive."""
    idx_a = pd.date_range("2024-01-01", periods=5, freq="D")
    idx_b = pd.date_range("2024-01-03", periods=5, freq="D")
    a = pd.Series([0.01, 0.02, 0.03, 0.04, 0.05], index=idx_a)
    b = pd.Series([0.10, 0.20, 0.30, 0.40, 0.50], index=idx_b)
    aligned_a, aligned_b = align_returns(a, b)
    assert list(aligned_a.index) == list(pd.date_range("2024-01-03", periods=3, freq="D"))
    assert aligned_a.tolist() == [0.03, 0.04, 0.05]
    assert aligned_b.tolist() == [0.10, 0.20, 0.30]


def test_align_returns_drops_nan_rows() -> None:
    idx = pd.date_range("2024-01-01", periods=4, freq="D")
    a = pd.Series([0.01, np.nan, 0.03, 0.04], index=idx)
    b = pd.Series([0.10, 0.20, np.nan, 0.40], index=idx)
    aligned_a, aligned_b = align_returns(a, b)
    assert len(aligned_a) == 2
    assert aligned_a.tolist() == [0.01, 0.04]
    assert aligned_b.tolist() == [0.10, 0.40]


def test_align_returns_insufficient_overlap_raises() -> None:
    a = pd.Series([0.01, 0.02], index=pd.date_range("2024-01-01", periods=2, freq="D"))
    b = pd.Series([0.01, 0.02], index=pd.date_range("2024-02-01", periods=2, freq="D"))
    with pytest.raises(ValueError, match="overlapping"):
        align_returns(a, b)
