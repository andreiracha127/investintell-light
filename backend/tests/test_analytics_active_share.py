"""Tests for app.analytics.active_share."""

import pytest

from app.analytics import active_share


def test_active_share_identical_portfolios_is_zero() -> None:
    weights = {"AAPL": 0.5, "MSFT": 0.5}
    assert active_share(weights, weights) == pytest.approx(0.0, abs=1e-12)


def test_active_share_disjoint_portfolios_is_one() -> None:
    """No overlap => 0.5 * (sum|p| + sum|b|) = 0.5 * (1 + 1) = 1.0 (decimal)."""
    portfolio = {"AAPL": 0.6, "MSFT": 0.4}
    benchmark = {"GOOG": 0.7, "AMZN": 0.3}
    assert active_share(portfolio, benchmark) == pytest.approx(1.0, rel=1e-12)


def test_active_share_matches_half_sum_abs_diff() -> None:
    portfolio = {"AAPL": 0.5, "MSFT": 0.3, "TSLA": 0.2}
    benchmark = {"AAPL": 0.4, "MSFT": 0.4, "GOOG": 0.2}
    # union ids: AAPL |0.5-0.4|=0.1, MSFT |0.3-0.4|=0.1, TSLA |0.2-0|=0.2,
    # GOOG |0-0.2|=0.2 => sum=0.6 => active_share = 0.3
    assert active_share(portfolio, benchmark) == pytest.approx(0.3, rel=1e-12)


def test_active_share_is_decimal_fraction_in_unit_range() -> None:
    portfolio = {"AAPL": 0.9, "MSFT": 0.1}
    benchmark = {"AAPL": 0.1, "MSFT": 0.9}
    result = active_share(portfolio, benchmark)
    assert 0.0 <= result <= 1.0


def test_active_share_empty_portfolio_raises() -> None:
    with pytest.raises(ValueError, match="empty|at least one"):
        active_share({}, {"AAPL": 1.0})


def test_active_share_empty_benchmark_raises() -> None:
    with pytest.raises(ValueError, match="empty|at least one"):
        active_share({"AAPL": 1.0}, {})


def test_active_share_weight_sum_out_of_range_raises() -> None:
    with pytest.raises(ValueError, match="sum to 1"):
        active_share({"AAPL": 0.5, "MSFT": 0.2}, {"AAPL": 1.0})  # portfolio sums 0.7


def test_active_share_nan_weight_raises() -> None:
    with pytest.raises(ValueError, match="finite|NaN"):
        active_share({"AAPL": float("nan"), "MSFT": 0.5}, {"AAPL": 1.0})
