"""Tests for app.analytics.benchmark_composite."""

import pandas as pd
import pytest

from app.analytics import composite_benchmark_nav


def _series(values: list[float], start: str = "2024-01-01") -> pd.Series:
    return pd.Series(values, index=pd.date_range(start, periods=len(values), freq="B"))


def test_composite_two_equal_blocks_compounds_weighted_returns() -> None:
    """50/50 composite return each day is the weighted mean of block returns;
    NAV compounds from inception_nav."""
    a = _series([0.01, 0.02, -0.01])
    b = _series([0.03, 0.00, 0.01])
    nav = composite_benchmark_nav({"A": 0.5, "B": 0.5}, {"A": a, "B": b}, inception_nav=1000.0)
    assert list(nav.index) == list(a.index)
    expected_returns = [0.5 * 0.01 + 0.5 * 0.03, 0.5 * 0.02 + 0.5 * 0.00, 0.5 * -0.01 + 0.5 * 0.01]
    cur = 1000.0
    for i, r in enumerate(expected_returns):
        cur *= 1.0 + r
        assert nav.iloc[i] == pytest.approx(cur, abs=1e-9)


def test_composite_weights_must_sum_to_one() -> None:
    a = _series([0.01, 0.02])
    b = _series([0.03, 0.00])
    with pytest.raises(ValueError, match="sum to 1.0"):
        composite_benchmark_nav({"A": 0.5, "B": 0.4}, {"A": a, "B": b})


def test_composite_latest_common_inception() -> None:
    """The composite starts at the latest inception across blocks (block B
    starts 2 business days later -> composite has 3 points, not 5)."""
    a = _series([0.01, 0.02, 0.03, 0.01, 0.02], start="2024-01-01")
    b = _series([0.00, 0.01, 0.02], start="2024-01-03")  # 2 B-days later
    nav = composite_benchmark_nav({"A": 0.5, "B": 0.5}, {"A": a, "B": b})
    assert len(nav) == 3
    assert nav.index[0] == b.index[0]


def test_composite_day_below_active_floor_is_skipped() -> None:
    """A day where only a 0.3-weight block is present (< 50% floor) is dropped
    (no forward-fill amplification). Block B (0.7 weight) is missing the middle
    date, so the middle day carries only A's 0.3 weight and is skipped."""
    idx = pd.date_range("2024-01-01", periods=3, freq="B")
    a = pd.Series([0.01, 0.02, 0.03], index=idx)
    b = pd.Series([0.05, 0.06], index=idx[[0, 2]])  # missing the middle date
    nav = composite_benchmark_nav({"A": 0.3, "B": 0.7}, {"A": a, "B": b})
    assert len(nav) == 2
    assert idx[1] not in nav.index


def test_composite_renormalizes_above_floor() -> None:
    """A day with >=50% active weight renormalizes the partial composite up to
    full weight."""
    idx = pd.date_range("2024-01-01", periods=2, freq="B")
    a = pd.Series([0.01, 0.02], index=idx)
    b = pd.Series([0.05], index=idx[[0]])  # missing the 2nd date
    nav = composite_benchmark_nav({"A": 0.7, "B": 0.3}, {"A": a, "B": b}, inception_nav=1000.0)
    # Day 1: full -> 0.7*0.01 + 0.3*0.05 = 0.022
    # Day 2: only A (0.7 >= 0.5 floor) -> renormalize 0.7*0.02 * (1.0/0.7) = 0.02
    assert nav.iloc[0] == pytest.approx(1000.0 * 1.022, abs=1e-9)
    assert nav.iloc[1] == pytest.approx(1000.0 * 1.022 * 1.02, abs=1e-9)


def test_composite_empty_inputs_raise() -> None:
    with pytest.raises(ValueError, match="at least one block"):
        composite_benchmark_nav({}, {})
