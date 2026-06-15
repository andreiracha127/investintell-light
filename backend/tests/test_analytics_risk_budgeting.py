"""Tier 2 risk-budgeting tests (T2B): variance MCTR/PCTR + Sharpe-implied
returns, and ETL MCETL/PCETL + STARR + ETL-implied returns.

All math is pure numpy on a T×N daily scenario matrix (the same matrix the
optimizer assembles in app.services.portfolio_builder). Vol-like / ETL-like
outputs are at the DAILY scale of the input; annualization is the caller's
job (TRADING_DAYS = 252).
"""

import numpy as np
import pandas as pd
import pytest

from app.analytics import risk_budgeting as rb
from app.analytics.portfolio import risk_contributions


def _scenarios(seed: int = 7, t: int = 600, n: int = 4) -> np.ndarray:
    """Seeded daily-return scenario matrix with mild cross-correlation."""
    rng = np.random.default_rng(seed)
    base = rng.normal(0.0, 0.01, size=(t, 1))
    idio = rng.normal(0.0, 0.008, size=(t, n))
    vols = np.array([0.5, 1.0, 1.5, 2.0])
    return base * vols + idio


def _diag_scenarios(vols: np.ndarray, t: int = 2000, seed: int = 3) -> np.ndarray:
    """Independent columns with the given per-asset daily vols (≈ diagonal Σ)."""
    rng = np.random.default_rng(seed)
    return rng.normal(0.0, 1.0, size=(t, vols.size)) * vols


# ── variance decomposition (MCTR / PCTR) ─────────────────────────────────────


def test_pctr_sums_to_one() -> None:
    scen = _scenarios()
    w = np.array([0.4, 0.3, 0.2, 0.1])
    dec = rb.variance_risk_budget(w, scen)
    assert abs(float(dec.pctr.sum()) - 1.0) < 1e-9


def test_mctr_equals_sigma_w_over_sigma_p() -> None:
    scen = _scenarios()
    w = np.array([0.25, 0.25, 0.25, 0.25])
    cov = np.cov(scen, rowvar=False, ddof=1)
    sigma_w = cov @ w
    sigma_p = float(np.sqrt(w @ cov @ w))
    dec = rb.variance_risk_budget(w, scen)
    np.testing.assert_allclose(dec.mctr, sigma_w / sigma_p, rtol=1e-10, atol=1e-12)
    assert abs(dec.portfolio_volatility - sigma_p) < 1e-12


def test_ctr_sums_to_sigma_p() -> None:
    scen = _scenarios()
    w = np.array([0.4, 0.3, 0.2, 0.1])
    dec = rb.variance_risk_budget(w, scen)
    assert abs(float(dec.ctr.sum()) - dec.portfolio_volatility) < 1e-12


def test_pctr_matches_existing_risk_contributions() -> None:
    """PCTR must reproduce app.analytics.portfolio.risk_contributions exactly."""
    scen = _scenarios()
    w = np.array([0.5, 0.2, 0.2, 0.1])
    cols = ["A", "B", "C", "D"]
    returns = pd.DataFrame(scen, columns=cols)
    ctr = risk_contributions(returns, dict(zip(cols, w, strict=True)))
    dec = rb.variance_risk_budget(w, scen)
    for i, col in enumerate(cols):
        assert abs(float(dec.pctr[i]) - ctr[col]) < 1e-9


def test_diagonal_sigma_closed_form() -> None:
    """For (near-)independent assets PCTR_i ≈ w_i² σ_i² / σ_p².

    The columns are independent in the population, but a finite 2000-row sample
    still carries residual off-diagonal covariance (cross-correlations up to
    ~0.02 under numpy 2.x), so the full-covariance Euler PCTR the function
    computes differs from the diagonal-only closed form by a few percent (~4%
    here). The EXACT full-covariance formula is pinned by
    test_mctr_equals_sigma_w_over_sigma_p (rtol=1e-10) and
    test_pctr_matches_existing_risk_contributions (abs<1e-9); this test only
    asserts the diagonal approximation holds to finite-sample tolerance, so the
    original rtol=1e-6 was unattainable by construction.
    """
    vols = np.array([0.01, 0.02, 0.04])
    scen = _diag_scenarios(vols)
    w = np.array([0.5, 0.3, 0.2])
    cov = np.cov(scen, rowvar=False, ddof=1)
    var_p = float(w @ cov @ w)
    expected_pctr = (w**2 * np.diag(cov)) / var_p
    dec = rb.variance_risk_budget(w, scen)
    np.testing.assert_allclose(dec.pctr, expected_pctr, rtol=5e-2, atol=1e-9)


def test_variance_budget_rejects_short_matrix() -> None:
    scen = np.zeros((1, 3))
    with pytest.raises(ValueError, match="at least 2 rows"):
        rb.variance_risk_budget(np.array([0.5, 0.3, 0.2]), scen)


def test_variance_budget_rejects_nan() -> None:
    scen = _scenarios()
    scen[0, 0] = np.nan
    with pytest.raises(ValueError, match="NaN or infinite"):
        rb.variance_risk_budget(np.array([0.25, 0.25, 0.25, 0.25]), scen)


def test_variance_budget_rejects_weight_length_mismatch() -> None:
    scen = _scenarios()
    with pytest.raises(ValueError, match="weights length"):
        rb.variance_risk_budget(np.array([0.5, 0.5]), scen)


def test_variance_budget_rejects_zero_variance_portfolio() -> None:
    scen = np.zeros((50, 2))  # constant (all-zero) returns → zero variance
    with pytest.raises(ValueError, match="portfolio variance"):
        rb.variance_risk_budget(np.array([0.5, 0.5]), scen)


# ── ETL decomposition (MCETL / PCETL) ────────────────────────────────────────

from app.analytics.risk import historical_cvar  # noqa: E402


def test_etl_contributions_sum_to_total_es() -> None:
    """w·MCETL sums EXACTLY to the (positive) portfolio ETL; PCETL sums to 1."""
    scen = _scenarios()
    w = np.array([0.4, 0.3, 0.2, 0.1])
    dec = rb.etl_risk_budget(w, scen, confidence=0.95)
    np.testing.assert_allclose(
        float((w * dec.mcetl).sum()), dec.portfolio_etl, rtol=1e-10, atol=1e-12
    )
    assert abs(float(dec.pcetl.sum()) - 1.0) < 1e-9
    assert dec.portfolio_etl > 0.0  # positive sign convention (loss magnitude)


def test_cetl_sums_to_portfolio_etl() -> None:
    scen = _scenarios()
    w = np.array([0.4, 0.3, 0.2, 0.1])
    dec = rb.etl_risk_budget(w, scen, confidence=0.95)
    assert abs(float(dec.cetl.sum()) - dec.portfolio_etl) < 1e-12


def test_portfolio_etl_matches_historical_cvar() -> None:
    """portfolio_etl equals app.analytics.historical_cvar on the same series."""
    scen = _scenarios()
    w = np.array([0.25, 0.25, 0.25, 0.25])
    dec = rb.etl_risk_budget(w, scen, confidence=0.95)
    port = pd.Series(scen @ w)
    assert abs(dec.portfolio_etl - historical_cvar(port, confidence=0.95)) < 1e-12


def test_pcetl_is_cetl_over_etl() -> None:
    scen = _scenarios()
    w = np.array([0.5, 0.2, 0.2, 0.1])
    dec = rb.etl_risk_budget(w, scen, confidence=0.95)
    np.testing.assert_allclose(
        dec.pcetl, (w * dec.mcetl) / dec.portfolio_etl, rtol=1e-10, atol=1e-12
    )


def test_etl_budget_requires_min_tail_rows() -> None:
    scen = _scenarios(t=9)
    with pytest.raises(ValueError, match="at least 10 rows"):
        rb.etl_risk_budget(np.array([0.25, 0.25, 0.25, 0.25]), scen, confidence=0.95)


def test_etl_budget_rejects_bad_confidence() -> None:
    scen = _scenarios()
    with pytest.raises(ValueError, match="confidence must be in"):
        rb.etl_risk_budget(np.array([0.25, 0.25, 0.25, 0.25]), scen, confidence=1.5)


def test_etl_budget_rejects_nan() -> None:
    scen = _scenarios()
    scen[5, 2] = np.inf
    with pytest.raises(ValueError, match="NaN or infinite"):
        rb.etl_risk_budget(np.array([0.25, 0.25, 0.25, 0.25]), scen, confidence=0.95)


# ── STARR ────────────────────────────────────────────────────────────────────


def test_starr_positive_when_excess_positive() -> None:
    scen = _scenarios()
    w = np.array([0.25, 0.25, 0.25, 0.25])
    # Explicit annualized portfolio expected return well above rf.
    starr = rb.portfolio_starr(
        w, scen, portfolio_return_ann=0.10, risk_free_rate=0.04, confidence=0.95
    )
    assert starr > 0.0


def test_starr_negative_when_excess_negative() -> None:
    scen = _scenarios()
    w = np.array([0.25, 0.25, 0.25, 0.25])
    starr = rb.portfolio_starr(
        w, scen, portfolio_return_ann=0.01, risk_free_rate=0.04, confidence=0.95
    )
    assert starr < 0.0


def test_starr_equals_excess_over_annualized_etl() -> None:
    scen = _scenarios()
    w = np.array([0.4, 0.3, 0.2, 0.1])
    dec = rb.etl_risk_budget(w, scen, confidence=0.95)
    etl_ann = dec.portfolio_etl * rb.TRADING_DAYS
    expected = (0.08 - 0.04) / etl_ann
    starr = rb.portfolio_starr(
        w, scen, portfolio_return_ann=0.08, risk_free_rate=0.04, confidence=0.95
    )
    assert abs(starr - expected) < 1e-10


def test_starr_rejects_nonpositive_etl_tail() -> None:
    # All-positive scenarios → loss tail has non-negative mean → ETL <= 0.
    scen = np.abs(_scenarios()) + 0.001
    w = np.array([0.25, 0.25, 0.25, 0.25])
    with pytest.raises(ValueError, match="non-positive portfolio ETL"):
        rb.portfolio_starr(
            w, scen, portfolio_return_ann=0.08, risk_free_rate=0.04, confidence=0.95
        )


def test_starr_rejects_nonfinite_return() -> None:
    scen = _scenarios()
    w = np.array([0.25, 0.25, 0.25, 0.25])
    with pytest.raises(ValueError, match="must be finite"):
        rb.portfolio_starr(
            w, scen, portfolio_return_ann=np.nan, risk_free_rate=0.04, confidence=0.95
        )
