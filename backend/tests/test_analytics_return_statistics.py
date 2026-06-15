"""Tests for app.analytics.return_statistics (eVestment ratios)."""

import numpy as np
import pandas as pd
import pytest

from app.analytics import (
    geometric_mean_monthly,
    jensen_alpha,
    omega_ratio,
    sterling_ratio,
    treynor_ratio,
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
