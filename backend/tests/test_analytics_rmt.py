"""Unit tests for the shared RMT analytics module (app.analytics.rmt).

Ported/condensed from legacy correlation_regime_service: constant-correlation
Ledoit-Wolf 2003 shrinkage, Marchenko-Pastur denoise, absorption ratio, and
the MP signal-eigenvalue count. Pure numpy — no I/O, no DB.
"""

import numpy as np
import pytest

from app.analytics import rmt


def _factor_returns(t: int, n: int, load: float = 0.6, seed: int = 0) -> np.ndarray:
    """(T,N) returns with a single common factor — strong cross-correlation."""
    rng = np.random.default_rng(seed)
    common = rng.standard_normal((t, 1))
    idio = rng.standard_normal((t, n))
    return load * common + (1.0 - load) * idio


# ── constant-correlation Ledoit-Wolf 2003 ────────────────────────────────────


def test_lw_constant_correlation_returns_psd_and_intensity_in_unit_interval() -> None:
    x = _factor_returns(60, 4)
    cov, delta = rmt.ledoit_wolf_constant_correlation(x)
    assert cov.shape == (4, 4)
    np.testing.assert_allclose(cov, cov.T, atol=1e-12)
    assert 0.0 <= delta <= 1.0
    assert np.linalg.eigvalsh(cov).min() > -1e-10


def test_lw_constant_correlation_preserves_offdiagonal_sign() -> None:
    """Unlike sklearn's scaled-identity target, the constant-correlation
    target keeps cross-asset covariance (off-diagonals stay non-trivial)."""
    x = _factor_returns(60, 4, load=0.8)
    cov, delta = rmt.ledoit_wolf_constant_correlation(x)
    off = cov[np.triu_indices(4, k=1)]
    assert (off > 0).all()
    assert delta > 0.0  # short window + structure ⇒ non-zero shrinkage


def test_lw_constant_correlation_rejects_too_few_rows() -> None:
    with pytest.raises(ValueError, match="at least 2"):
        rmt.ledoit_wolf_constant_correlation(np.zeros((1, 3)))


def test_lw_constant_correlation_rejects_nan() -> None:
    x = _factor_returns(60, 3)
    x[5, 1] = np.nan
    with pytest.raises(ValueError, match="NaN"):
        rmt.ledoit_wolf_constant_correlation(x)


# ── Marchenko-Pastur denoise ─────────────────────────────────────────────────


def test_mp_denoise_returns_correlation_matrix_unit_diagonal() -> None:
    x = _factor_returns(120, 6)
    corr = np.corrcoef(x, rowvar=False)
    q = 6 / 120
    denoised = rmt.marchenko_pastur_denoise(corr, q)
    np.testing.assert_allclose(np.diag(denoised), np.ones(6), atol=1e-9)
    np.testing.assert_allclose(denoised, denoised.T, atol=1e-12)
    assert np.linalg.eigvalsh(denoised).min() > -1e-10


def test_mp_denoise_collapses_noise_eigenvalues() -> None:
    """Eigenvalues below the MP upper bound are flattened to one value, so the
    denoised spectrum has fewer DISTINCT small eigenvalues than the raw one."""
    x = _factor_returns(80, 8)
    corr = np.corrcoef(x, rowvar=False)
    q = 8 / 80
    raw_eigs = np.sort(np.linalg.eigvalsh(corr))
    den_eigs = np.sort(np.linalg.eigvalsh(rmt.marchenko_pastur_denoise(corr, q)))
    lambda_plus = (1 + np.sqrt(q)) ** 2
    raw_noise = raw_eigs[raw_eigs < lambda_plus]
    den_noise = den_eigs[den_eigs < lambda_plus]
    assert raw_noise.size >= 2
    assert raw_noise.std() > den_noise.std()


def test_mp_denoise_rejects_bad_q() -> None:
    corr = np.eye(3)
    with pytest.raises(ValueError, match="q must be > 0"):
        rmt.marchenko_pastur_denoise(corr, 0.0)


# ── absorption ratio ─────────────────────────────────────────────────────────


def test_absorption_ratio_high_for_single_factor_market() -> None:
    x = _factor_returns(200, 10, load=0.9)
    corr = np.corrcoef(x, rowvar=False)
    ar = rmt.absorption_ratio(corr)
    assert 0.0 < ar <= 1.0
    assert ar > 0.5  # one dominant factor ⇒ top eigenvalues absorb most variance


def test_absorption_ratio_low_for_independent_assets() -> None:
    rng = np.random.default_rng(1)
    x = rng.standard_normal((300, 10))  # ~independent
    ar = rmt.absorption_ratio(np.corrcoef(x, rowvar=False))
    assert ar < 0.5


def test_absorption_ratio_respects_explicit_k() -> None:
    corr = np.eye(5)
    # Identity: each eigenvalue = 1, total = 5; top-1 absorbs exactly 0.2.
    assert rmt.absorption_ratio(corr, k=1) == pytest.approx(0.2, abs=1e-9)
    assert rmt.absorption_ratio(corr, k=2) == pytest.approx(0.4, abs=1e-9)


def test_absorption_ratio_rejects_empty() -> None:
    with pytest.raises(ValueError, match="non-empty square"):
        rmt.absorption_ratio(np.zeros((0, 0)))


# ── MP signal-eigenvalue count ───────────────────────────────────────────────


def test_mp_signal_count_counts_eigenvalues_above_bound() -> None:
    x = _factor_returns(150, 6, load=0.85)
    corr = np.corrcoef(x, rowvar=False)
    q = 6 / 150
    n_signal, lambda_plus = rmt.mp_signal_eigenvalues(corr, q)
    assert lambda_plus == pytest.approx((1 + np.sqrt(q)) ** 2, abs=1e-9)
    assert 1 <= n_signal < 6  # at least the factor, not all six


def test_mp_signal_count_rejects_bad_q() -> None:
    with pytest.raises(ValueError, match="q must be > 0"):
        rmt.mp_signal_eigenvalues(np.eye(3), -0.1)
