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
    realized_cvar,
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


# --- exact Rockafellar–Uryasev realized_cvar (T1C) ----------------------------

# Fixed 30-point return series: (1-0.95)*30 = 1.5 (non-integer tail) so the
# exact RU estimator DIVERGES from the naive tail-mean historical_cvar.
_RU_SERIES_30 = [
    -0.012459, -0.004381, 0.017143, 0.002922, 0.012363, 0.007902, -0.007874,
    0.007445, -0.003716, -0.003791, 0.001663, -0.019437, 0.015898, -0.008324,
    0.013404, 0.002172, 0.020316, -0.00818, -0.003653, 0.004791, -0.028297,
    0.011163, 0.020441, 0.015048, 0.010212, -0.001498, 0.017065, 0.014362,
    0.005504, 0.000466,
]


def _ru_reference(returns: pd.Series, confidence: float) -> float:
    """Independent RU empirical CVaR, mirroring the optimizer objective.

    Single-asset losses = -returns; CVaR_alpha = var_loss + sum of positive
    excess over the upper-quantile VaR, scaled by 1/((1-alpha)*T). Positive
    decimal fraction (same sign convention as the production estimator).
    """
    losses = -returns.to_numpy(dtype=float)
    t = losses.size
    var_loss = float(np.quantile(losses, confidence, method="higher"))
    excess = np.maximum(losses - var_loss, 0.0)
    return var_loss + float(excess.sum()) / ((1.0 - confidence) * t)


def test_realized_cvar_matches_ru_reference_non_integer_tail() -> None:
    """On a 30-point series (1.5 expected tail obs) realized_cvar equals the
    exact Rockafellar–Uryasev value used by the optimizer objective."""
    returns = _dated(_RU_SERIES_30)
    expected = _ru_reference(returns, 0.95)
    assert realized_cvar(returns, 0.95) == pytest.approx(expected, abs=1e-12)
    # Pin the literal so a regression to tail-mean is caught loudly.
    assert realized_cvar(returns, 0.95) == pytest.approx(
        0.025343666666666667, abs=1e-12
    )


def test_realized_cvar_diverges_from_naive_tail_mean() -> None:
    """The whole point of the swap: with a non-integer expected tail size the
    exact RU estimator differs from the naive historical_cvar tail-mean."""
    returns = _dated(_RU_SERIES_30)
    assert realized_cvar(returns, 0.95) != pytest.approx(
        historical_cvar(returns, 0.95), abs=1e-9
    )
    # naive tail-mean of this series is 0.023867 (mean of the worst 2).
    assert historical_cvar(returns, 0.95) == pytest.approx(0.023867, abs=1e-9)
    assert realized_cvar(returns, 0.95) > historical_cvar(returns, 0.95)


def test_realized_cvar_integer_tail_matches_tail_mean() -> None:
    """Edge case: when (1-alpha)*T is an integer (here 20*0.05 = 1.0) the RU
    estimator and the tail-mean coincide (single worst observation)."""
    returns = _dated(
        [
            0.012, -0.034, 0.008, -0.021, 0.005, -0.058, 0.017, -0.009, 0.003,
            -0.045, 0.022, -0.011, 0.006, -0.073, 0.014, -0.002, 0.019, -0.027,
            0.001, -0.039,
        ]
    )
    assert realized_cvar(returns, 0.95) == pytest.approx(0.073, abs=1e-12)
    assert realized_cvar(returns, 0.95) == pytest.approx(
        historical_cvar(returns, 0.95), abs=1e-12
    )


def test_realized_cvar_at_least_var() -> None:
    """CVaR >= VaR (expected shortfall dominates the threshold)."""
    r = _random_returns(500, seed=17)
    assert realized_cvar(r, 0.95) >= historical_var(r, 0.95)


def test_realized_cvar_positive_for_lossy_series() -> None:
    assert realized_cvar(_random_returns(), 0.95) > 0


def test_realized_cvar_monotonicity() -> None:
    """CVaR(99%) >= CVaR(95%): a deeper tail is at least as costly."""
    r = _random_returns(500, seed=17)
    assert realized_cvar(r, 0.99) >= realized_cvar(r, 0.95)


def test_realized_cvar_short_input_raises() -> None:
    with pytest.raises(ValueError, match="at least 10"):
        realized_cvar(_dated([0.01] * 9))


def test_realized_cvar_bad_confidence_raises() -> None:
    with pytest.raises(ValueError, match="confidence"):
        realized_cvar(_random_returns(), confidence=95.0)


def test_realized_cvar_nan_input_raises() -> None:
    with pytest.raises(ValueError, match="NaN"):
        realized_cvar(_dated([0.01, np.nan, -0.02] + [0.0] * 7))


# --- Sharpe ratio (T1A-1) ----------------------------------------------------

from app.analytics import DEFAULT_RISK_FREE_RATE, sharpe_ratio  # noqa: E402


def test_sharpe_ratio_matches_manual_formula() -> None:
    """sharpe = mean(excess)/std(excess, ddof=1) * sqrt(252), excess = r - rf/252."""
    returns = _random_returns(252, seed=11)
    rf = 0.04
    excess = returns.to_numpy(dtype=float) - rf / 252
    expected = float(np.mean(excess) / np.std(excess, ddof=1) * math.sqrt(252))
    assert sharpe_ratio(returns, risk_free_rate=rf) == pytest.approx(expected, rel=1e-12)


def test_sharpe_ratio_default_rf_is_canonical() -> None:
    assert DEFAULT_RISK_FREE_RATE == 0.04
    returns = _random_returns(252, seed=12)
    assert sharpe_ratio(returns) == pytest.approx(
        sharpe_ratio(returns, risk_free_rate=0.04), rel=1e-12
    )


def test_sharpe_ratio_higher_for_higher_mean() -> None:
    base = _random_returns(252, seed=13)
    shifted = base + 0.001  # shift mean up, same vol
    assert sharpe_ratio(shifted) > sharpe_ratio(base)


def test_sharpe_ratio_short_input_raises() -> None:
    with pytest.raises(ValueError, match="at least 10"):
        sharpe_ratio(_dated([0.01] * 9))


def test_sharpe_ratio_zero_vol_raises() -> None:
    with pytest.raises(ValueError, match="zero volatility|undefined"):
        sharpe_ratio(_dated([0.01] * 30))


def test_sharpe_ratio_nan_input_raises() -> None:
    with pytest.raises(ValueError, match="NaN"):
        sharpe_ratio(_dated([0.01, np.nan, 0.02] * 5))


# --- Sortino ratio (T1A-2) ---------------------------------------------------

from app.analytics import sortino_ratio  # noqa: E402


def test_sortino_ratio_matches_manual_formula() -> None:
    """sortino = mean(excess)/TDD * sqrt(252); TDD = sqrt(mean(min(excess,0)^2))."""
    returns = _random_returns(252, seed=21)
    rf = 0.04
    excess = returns.to_numpy(dtype=float) - rf / 252
    shortfall = np.minimum(excess, 0.0)
    tdd = float(np.sqrt(np.mean(shortfall**2)))
    expected = float(np.mean(excess) / tdd * math.sqrt(252))
    assert sortino_ratio(returns, risk_free_rate=rf) == pytest.approx(expected, rel=1e-12)


def test_sortino_ratio_ge_sharpe_for_this_seed() -> None:
    """For seed=22 (positive-Sharpe series) the Target Downside Deviation is
    below the total excess std, so Sortino > Sharpe. This is NOT a universal
    property (it inverts for negative-mean series), hence the fixed seed."""
    returns = _random_returns(252, seed=22)
    assert sortino_ratio(returns) >= sharpe_ratio(returns) - 1e-9


def test_sortino_ratio_short_input_raises() -> None:
    with pytest.raises(ValueError, match="at least 10"):
        sortino_ratio(_dated([0.01] * 9))


def test_sortino_ratio_no_downside_raises() -> None:
    """All-positive excess => TDD == 0 => undefined (fail loud, never inf/NaN)."""
    with pytest.raises(ValueError, match="downside|undefined"):
        sortino_ratio(_dated([0.05] * 30))  # 0.05 > rf/252, no shortfall


def test_sortino_ratio_nan_input_raises() -> None:
    with pytest.raises(ValueError, match="NaN"):
        sortino_ratio(_dated([0.01, np.nan, -0.02] * 5))
