"""Tests for app.analytics.return_statistics (eVestment ratios)."""

import numpy as np
import pandas as pd
import pytest

from app.analytics import (
    down_proficiency_ratio,
    geometric_mean_monthly,
    jensen_alpha,
    omega_ratio,
    r_squared,
    sterling_ratio,
    treynor_ratio,
    up_proficiency_ratio,
)


def _daily(n: int, seed: int, mu: float = 0.0005, sigma: float = 0.01) -> pd.Series:
    rng = np.random.default_rng(seed)
    return pd.Series(
        rng.normal(mu, sigma, n),
        index=pd.date_range("2020-01-01", periods=n, freq="B"),
    )


def test_geometric_mean_monthly_matches_formula() -> None:
    daily = _daily(252, seed=1)
    from app.analytics import to_monthly_returns

    monthly = to_monthly_returns(daily)
    expected = float(np.prod(1.0 + monthly.to_numpy()) ** (1.0 / len(monthly)) - 1.0)
    assert geometric_mean_monthly(daily) == pytest.approx(expected, abs=1e-12)


def test_omega_ratio_gains_over_losses() -> None:
    """Omega = sum(max(r-MAR,0)) / sum(|min(r-MAR,0)|) on monthly returns."""
    daily = _daily(252, seed=2)
    from app.analytics import to_monthly_returns

    monthly = to_monthly_returns(daily).to_numpy()
    gains = float(np.sum(np.maximum(monthly, 0.0)))
    losses = float(np.sum(np.abs(np.minimum(monthly, 0.0))))
    assert omega_ratio(daily, mar=0.0) == pytest.approx(gains / losses, abs=1e-9)


def test_omega_ratio_all_gains_raises() -> None:
    daily = pd.Series([0.01] * 42, index=pd.date_range("2020-01-01", periods=42, freq="B"))
    with pytest.raises(ValueError, match="no downside"):
        omega_ratio(daily)


def test_sterling_ratio_kestner_denominator() -> None:
    """Sterling = ann_return / |avg_yearly_max_dd - 0.10|; denominator uses the
    additive 10% cushion (Kestner)."""
    daily = _daily(504, seed=3)  # 2 years
    val = sterling_ratio(daily)
    # Reconstruct expected: geometric annualized return over full sample.
    arr = daily.to_numpy(dtype=float)
    ann = float(np.prod(1.0 + arr) ** (252 / len(arr)) - 1.0)
    # Yearly max DDs on the two 252-day NAV chunks (end-anchored).
    n_years = len(arr) // 252
    trimmed = arr[-n_years * 252 :]
    dds = []
    for k in range(n_years):
        chunk = trimmed[k * 252 : (k + 1) * 252]
        navs = np.concatenate([[1.0], np.cumprod(1.0 + chunk)])
        run_max = np.maximum.accumulate(navs)
        dds.append(float(np.min(navs / run_max - 1.0)))
    denom = abs(float(np.mean(dds)) - 0.10)
    assert val == pytest.approx(ann / denom, abs=1e-9)


def test_sterling_ratio_requires_one_year() -> None:
    daily = _daily(200, seed=4)
    with pytest.raises(ValueError, match="at least 252"):
        sterling_ratio(daily)


def test_treynor_and_jensen_against_regression() -> None:
    """Treynor = (ann_return - rf) / beta_monthly; Jensen = annualized monthly
    alpha. Cross-checked against a direct monthly covariance/var beta."""
    daily = _daily(504, seed=5)
    bench = _daily(504, seed=6)
    from app.analytics import to_monthly_returns

    r = to_monthly_returns(daily)
    bm = to_monthly_returns(bench)
    n = min(len(r), len(bm))
    rv = r.to_numpy()[:n]
    bv = bm.to_numpy()[:n]
    beta_m = float(np.cov(rv, bv, ddof=1)[0, 1] / np.var(bv, ddof=1))
    geom = float(np.prod(1.0 + rv) ** (1.0 / n) - 1.0)
    ann_return = (1.0 + geom) ** 12 - 1.0
    rf = 0.04
    assert treynor_ratio(daily, bench, risk_free_rate=rf) == pytest.approx(
        (ann_return - rf) / beta_m, abs=1e-6
    )
    rf_monthly = rf / 12.0
    monthly_alpha = float(np.mean(rv) - rf_monthly - beta_m * (np.mean(bv) - rf_monthly))
    assert jensen_alpha(daily, bench, risk_free_rate=rf) == pytest.approx(
        monthly_alpha * 12.0, abs=1e-8
    )


def test_treynor_requires_min_months() -> None:
    daily = _daily(210, seed=7)   # 10 months (210 // 21)
    bench = _daily(210, seed=8)
    with pytest.raises(ValueError, match="at least 12"):
        treynor_ratio(daily, bench)


def test_proficiency_ratios_hit_rate() -> None:
    """Up = fraction of benchmark-UP months the fund beat the benchmark;
    Down = same over benchmark-DOWN months. Both are decimal fractions in [0,1]."""
    daily = _daily(504, seed=11)
    bench = _daily(504, seed=12)
    from app.analytics import to_monthly_returns

    r = to_monthly_returns(daily)
    bm = to_monthly_returns(bench)
    n = min(len(r), len(bm))
    rv = r.to_numpy()[:n]
    bv = bm.to_numpy()[:n]
    up_mask = bv >= 0
    down_mask = bv < 0
    exp_up = float(np.sum(rv[up_mask] > bv[up_mask]) / np.sum(up_mask))
    exp_down = float(np.sum(rv[down_mask] > bv[down_mask]) / np.sum(down_mask))
    assert up_proficiency_ratio(daily, bench) == pytest.approx(exp_up, abs=1e-9)
    assert down_proficiency_ratio(daily, bench) == pytest.approx(exp_down, abs=1e-9)
    assert 0.0 <= up_proficiency_ratio(daily, bench) <= 1.0
    assert 0.0 <= down_proficiency_ratio(daily, bench) <= 1.0


def test_r_squared_is_correlation_squared() -> None:
    daily = _daily(504, seed=13)
    bench = _daily(504, seed=14)
    from app.analytics import correlation, to_monthly_returns

    r = to_monthly_returns(daily)
    bm = to_monthly_returns(bench)
    n = min(len(r), len(bm))
    corr = correlation(r.iloc[:n], bm.iloc[:n])
    assert r_squared(daily, bench) == pytest.approx(corr**2, abs=1e-9)
    assert 0.0 <= r_squared(daily, bench) <= 1.0


def test_proficiency_requires_min_months() -> None:
    daily = _daily(210, seed=15)   # 10 months
    bench = _daily(210, seed=16)
    with pytest.raises(ValueError, match="at least 12"):
        up_proficiency_ratio(daily, bench)


def test_up_proficiency_no_up_months_raises() -> None:
    """A benchmark that is never up over the aligned months -> undefined up-ratio.
    The benchmark VARIES day to day (nonzero monthly variance) but every month
    compounds negative, so the up-months guard fires, not a variance guard."""
    idx = pd.date_range("2020-01-01", periods=12 * 21, freq="B")
    daily = pd.Series(np.full(12 * 21, 0.001), index=idx)
    rng = np.random.default_rng(99)
    bench_vals = -np.abs(rng.normal(0.002, 0.001, 12 * 21)) - 0.0005  # every day < 0
    bench = pd.Series(bench_vals, index=idx)
    with pytest.raises(ValueError, match="no benchmark-up months"):
        up_proficiency_ratio(daily, bench)
