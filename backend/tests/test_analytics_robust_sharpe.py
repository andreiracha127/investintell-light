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


# --- Cornish-Fisher adjustment direction -------------------------------------


def _left_tailed_returns() -> np.ndarray:
    """T=80 series with mild NEGATIVE skew (downside outliers)."""
    rng = np.random.default_rng(5)
    body = rng.standard_normal(78) * 0.02 + 0.008
    return np.concatenate([body, [-0.08, -0.10]])


def _right_tailed_returns() -> np.ndarray:
    """T=80 series with mild POSITIVE skew (upside outliers)."""
    rng = np.random.default_rng(5)
    body = rng.standard_normal(78) * 0.02 + 0.008
    return np.concatenate([body, [0.10, 0.12]])


def test_negative_skew_penalizes_cf_sharpe() -> None:
    """Left-tail risk inflates the CF sigma, so CF Sharpe < traditional Sharpe.

    skew(_left_tailed_returns()) ~ -1.31 (verified), z_cf ~ -1.88 (still
    negative, NOT clamped), so the comparison reflects the genuine CF math.
    """
    res = robust_sharpe(_left_tailed_returns(), rf_rate=0.0)
    assert res.skewness < 0
    assert res.sharpe_cornish_fisher < res.sharpe_traditional


def test_positive_skew_rewards_cf_sharpe() -> None:
    """Right-tail upside shrinks the CF sigma, so CF Sharpe > traditional.

    skew(_right_tailed_returns()) ~ +1.90 (verified) so |skew|>1.5 auto-routes
    the CI to jackknife, but z_cf ~ -0.90 stays negative (NOT clamped) so the
    CF point estimate is the genuine expansion; only the CI method differs.
    """
    res = robust_sharpe(_right_tailed_returns(), rf_rate=0.0)
    assert res.skewness > 0
    assert res.sharpe_cornish_fisher > res.sharpe_traditional


def test_symmetric_returns_cf_close_to_traditional() -> None:
    """Near-symmetric mesokurtic series: CF Sharpe ~ traditional Sharpe."""
    rng = np.random.default_rng(11)
    r = rng.normal(0.0, 0.03, 200)
    res = robust_sharpe(r, rf_rate=0.0)
    assert res.sharpe_cornish_fisher == pytest.approx(res.sharpe_traditional, rel=0.25)


# --- non-monotonic Cornish-Fisher clamp --------------------------------------


def test_cornish_fisher_non_monotonic_clamp() -> None:
    """Extreme positive skew/kurtosis makes z_CF >= 0 (the quantile expansion
    is non-monotonic). The module clamps sigma_CF to keep CF Sharpe finite and
    flags the result as degraded with reason 'cornish_fisher_non_monotonic'."""
    # 39 flat points + one huge positive outlier => skew ~ 6.33, excess kurt ~ 40
    # (verified). std is nonzero (the outlier), so the zero-vol guard does not
    # fire; T=40 >= 36 so CF is computed and z_cf ~ +1.71 >= 0 triggers the clamp.
    arr = np.array([0.01] * 39 + [2.0], dtype=float)
    res = robust_sharpe(arr, rf_rate=0.0)
    assert res.n_observations == 40
    assert res.degraded is True
    assert res.degraded_reason == "cornish_fisher_non_monotonic"
    # CF Sharpe stays finite despite the clamp.
    assert math.isfinite(res.sharpe_cornish_fisher)
    # Traditional Sharpe is still reported and finite.
    assert math.isfinite(res.sharpe_traditional)


# --- jackknife SE fallback ----------------------------------------------------


def test_explicit_jackknife_method() -> None:
    """Requesting jackknife yields a jackknife CI even for a large sample."""
    r = _normal_returns(120)
    res = robust_sharpe(r, rf_rate=0.0, ci_method="jackknife")
    assert res.ci_method == "jackknife"
    assert math.isfinite(res.ci_lower_95)
    assert math.isfinite(res.ci_upper_95)
    assert res.ci_lower_95 < res.sharpe_traditional < res.ci_upper_95


def test_auto_jackknife_when_T_below_60() -> None:
    """T=48 (>= 36, so CF computed) auto-falls-back to jackknife for the CI."""
    r = _normal_returns(48, seed=3)
    res = robust_sharpe(r, rf_rate=0.0)  # default ci_method="closed_form"
    assert res.n_observations == 48
    assert res.ci_method == "jackknife"
    assert math.isfinite(res.sharpe_cornish_fisher)  # CF still available at T>=36
    assert math.isfinite(res.ci_lower_95)


def test_auto_jackknife_when_skew_extreme() -> None:
    """|skew| > 1.5 on a large sample forces jackknife even when T >= 60."""
    rng = np.random.default_rng(9)
    body = rng.standard_normal(98) * 0.02 + 0.01
    r = np.concatenate([body, [0.5, 0.6]])  # heavy right tail -> |skew| ~ 6.39
    res = robust_sharpe(r, rf_rate=0.0)
    assert res.n_observations == 100
    assert abs(res.skewness) > 1.5
    assert res.ci_method == "jackknife"


def test_closed_form_retained_for_large_low_skew() -> None:
    """T=120, near-symmetric: stays closed_form (control for the triggers above)."""
    r = _normal_returns(120)
    res = robust_sharpe(r, rf_rate=0.0)
    assert res.ci_method == "closed_form"
    assert abs(res.skewness) <= 1.5
    assert res.n_observations >= 60


def test_jackknife_se_all_constant_returns_nan() -> None:
    """_jackknife_se returns NaN when fewer than 3 finite replicates survive.

    For an exactly-constant array every leave-one-out subset is constant, so
    every replicate variance is 0 -> every replicate is NaN -> < 3 finite ->
    SE is NaN. This is the deterministic unit of the degenerate-CI path
    (the end-to-end robust_sharpe path is floating-point-fragile; see the
    cluster open_questions). Note the helper has NO zero-vol guard — that guard
    lives in robust_sharpe, added in Task T2A-4 — so the helper is exercised
    directly here.
    """
    from app.analytics.robust_sharpe import _jackknife_se

    se = _jackknife_se(np.array([0.5] * 10, dtype=float), periods_per_year=12)
    assert math.isnan(se)
    # A healthy small sample yields a finite, positive SE.
    healthy = _normal_returns(48, seed=1)
    se_ok = _jackknife_se(healthy, periods_per_year=12)
    assert math.isfinite(se_ok)
    assert se_ok > 0.0


# --- tiered sample-size degradation ------------------------------------------


def test_empty_input_is_degraded_all_nan() -> None:
    """T=0 (empty or all-NaN) -> fully degraded, reason 'all_nan_or_empty'."""
    res = robust_sharpe(np.array([], dtype=float), rf_rate=0.0)
    assert res.n_observations == 0
    assert res.degraded is True
    assert res.degraded_reason == "all_nan_or_empty"
    assert math.isnan(res.sharpe_traditional)
    assert math.isnan(res.sharpe_cornish_fisher)


def test_all_nan_input_is_degraded() -> None:
    """A series of only NaNs strips to length 0."""
    res = robust_sharpe(np.array([float("nan")] * 20), rf_rate=0.0)
    assert res.n_observations == 0
    assert res.degraded_reason == "all_nan_or_empty"


def test_nans_are_stripped_then_counted() -> None:
    """Interior NaNs are dropped; n_observations counts only finite points."""
    rng = np.random.default_rng(2)
    clean = rng.normal(0.01, 0.04, 100)
    dirty = np.insert(clean, [10, 50, 90], np.nan)
    res = robust_sharpe(dirty, rf_rate=0.0)
    assert res.n_observations == 100


def test_below_12_best_effort_traditional_only() -> None:
    """T<12: traditional Sharpe is best-effort finite; CF/CI are NaN and the
    result is degraded with reason 'insufficient_observations'."""
    arr = np.array([0.01, 0.02, -0.01, 0.03, 0.0, 0.015, -0.005, 0.02], dtype=float)
    res = robust_sharpe(arr, rf_rate=0.0)
    assert res.n_observations == 8
    assert res.degraded is True
    assert res.degraded_reason == "insufficient_observations"
    assert math.isfinite(res.sharpe_traditional)
    assert math.isnan(res.sharpe_cornish_fisher)
    assert math.isnan(res.ci_lower_95)


def test_between_12_and_36_no_cornish_fisher() -> None:
    """12 <= T < 36: traditional Sharpe and moments are computed, but CF is
    not (insufficient observations for a stable expansion)."""
    r = _normal_returns(24, seed=4)
    res = robust_sharpe(r, rf_rate=0.0)
    assert res.n_observations == 24
    assert res.degraded is True
    assert res.degraded_reason == "insufficient_observations"
    assert math.isfinite(res.sharpe_traditional)
    assert math.isfinite(res.skewness)
    assert math.isfinite(res.excess_kurtosis)
    assert math.isnan(res.sharpe_cornish_fisher)


def test_zero_volatility_positive_mean_is_plus_inf() -> None:
    """Constant positive returns: zero vol -> +inf traditional Sharpe, degraded
    with reason 'zero_volatility', no division-by-zero crash."""
    res = robust_sharpe(np.array([0.02] * 40, dtype=float), rf_rate=0.0)
    assert res.n_observations == 40
    assert res.degraded is True
    assert res.degraded_reason == "zero_volatility"
    assert res.sharpe_traditional == float("inf")
    assert res.skewness == 0.0
    assert res.excess_kurtosis == 0.0


def test_zero_volatility_negative_mean_is_minus_inf() -> None:
    """Constant zero return with a positive rf -> negative excess -> -inf."""
    res = robust_sharpe(np.array([0.0] * 40, dtype=float), rf_rate=0.01)
    assert res.sharpe_traditional == float("-inf")
    assert res.degraded_reason == "zero_volatility"
