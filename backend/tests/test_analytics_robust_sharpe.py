"""Tests for app.analytics.robust_sharpe (Cornish-Fisher robust Sharpe)."""

import math

import numpy as np
import pytest
from scipy import stats

from app.analytics.robust_sharpe import (
    RobustSharpeResult,
    robust_sharpe,
)


def _normal_returns(n: int, mu: float = 0.01, sigma: float = 0.04, seed: int = 42) -> np.ndarray:
    rng = np.random.default_rng(seed)
    return rng.normal(mu, sigma, n)


# --- full-sample closed-form path --------------------------------------------


def test_closed_form_full_sample_basic() -> None:
    """T=120 near-normal series: closed_form CI, not degraded, sane fields.

    The Opdyke variance is positive for a near-normal sample, so the CI is
    finite and centered on the traditional (annualized) Sharpe ratio.
    """
    r = _normal_returns(120)
    res = robust_sharpe(r, rf_rate=0.0)
    assert isinstance(res, RobustSharpeResult)
    assert res.n_observations == 120
    assert res.ci_method == "closed_form"
    assert res.degraded is False
    assert res.degraded_reason is None
    # Traditional Sharpe equals mean/std * sqrt(12) computed independently.
    expected_sr = float(np.mean(r) / np.std(r, ddof=1) * math.sqrt(12))
    assert res.sharpe_traditional == expected_sr
    # CI brackets the point estimate.
    assert res.ci_lower_95 < res.sharpe_traditional < res.ci_upper_95
    # Moments match scipy unbiased estimators.
    assert res.skewness == float(stats.skew(r, bias=False))
    assert res.excess_kurtosis == float(stats.kurtosis(r, bias=False, fisher=True))
    # All fields finite for a healthy sample.
    for v in (
        res.sharpe_traditional,
        res.sharpe_cornish_fisher,
        res.ci_lower_95,
        res.ci_upper_95,
    ):
        assert math.isfinite(v)


def test_rf_none_treated_as_zero() -> None:
    """rf_rate=None must equal rf_rate=0.0 (legacy spec 1.3)."""
    r = _normal_returns(120)
    a = robust_sharpe(r, rf_rate=None)
    b = robust_sharpe(r, rf_rate=0.0)
    assert a.sharpe_traditional == b.sharpe_traditional
    assert a.sharpe_cornish_fisher == b.sharpe_cornish_fisher


def test_rf_rate_shifts_sharpe_down() -> None:
    """A positive per-period risk-free rate lowers excess return, hence Sharpe."""
    r = _normal_returns(120, mu=0.02)
    base = robust_sharpe(r, rf_rate=0.0)
    charged = robust_sharpe(r, rf_rate=0.01)
    assert charged.sharpe_traditional < base.sharpe_traditional


def test_periods_per_year_scales_traditional_sharpe() -> None:
    """Annualized Sharpe scales by sqrt(periods_per_year)."""
    r = _normal_returns(120)
    monthly = robust_sharpe(r, rf_rate=0.0, periods_per_year=12)
    daily = robust_sharpe(r, rf_rate=0.0, periods_per_year=252)
    assert daily.sharpe_traditional == pytest.approx(
        monthly.sharpe_traditional / math.sqrt(12) * math.sqrt(252)
    )
