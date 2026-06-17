"""Tests for engine.sigma_robust — RMT path when q=N/T>0.5, else Ledoit-Wolf;
always PSD-repaired; deterministic fallback.
"""

import numpy as np
import pytest

from app.optimizer import engine


def _factor_returns(t: int, n: int, load: float = 0.6, seed: int = 0) -> np.ndarray:
    rng = np.random.default_rng(seed)
    common = rng.standard_normal((t, 1))
    idio = rng.standard_normal((t, n))
    return load * common + (1.0 - load) * idio


def test_sigma_robust_low_q_matches_ledoit_wolf() -> None:
    """q = 5/400 = 0.0125 < 0.5 ⇒ the Ledoit-Wolf path (×252), PSD-repaired.

    sigma_robust always ends in repair_psd, so the low-q result must equal
    repair_psd(sigma_ledoit_wolf(...)) — NOT the bare LW (repair_psd may clamp
    the condition number on an ill-conditioned panel)."""
    x = _factor_returns(400, 5, seed=1)
    robust = engine.sigma_robust(x)
    lw = engine.repair_psd(engine.sigma_ledoit_wolf(x))
    np.testing.assert_allclose(robust, lw, atol=1e-10)


def test_sigma_robust_high_q_uses_rmt_path_and_is_psd() -> None:
    """q = 40/60 = 0.67 > 0.5 ⇒ RMT path; result differs from plain LW but
    stays PSD and symmetric, with the same annualization scale."""
    x = _factor_returns(60, 40, seed=2)
    robust = engine.sigma_robust(x)
    assert robust.shape == (40, 40)
    np.testing.assert_allclose(robust, robust.T, atol=1e-9)
    assert np.linalg.eigvalsh(robust).min() > -1e-9  # PSD after repair
    lw = engine.sigma_ledoit_wolf(x)
    assert not np.allclose(robust, lw)  # RMT denoise changed the estimate
    # Both are annualized (×252); the RMT denoise must not collapse or blow up
    # the per-asset variances — they stay within a factor of 2 of plain LW.
    np.testing.assert_array_less(np.diag(robust), np.diag(lw) * 2.0)
    np.testing.assert_array_less(np.diag(lw) * 0.5, np.diag(robust))


def test_sigma_robust_threshold_is_configurable() -> None:
    """Forcing q_threshold high keeps a high-q panel on the Ledoit-Wolf path
    (compared against the PSD-repaired LW, since sigma_robust always repairs)."""
    x = _factor_returns(60, 40, seed=3)
    forced_lw = engine.sigma_robust(x, q_threshold=10.0)
    lw = engine.repair_psd(engine.sigma_ledoit_wolf(x))
    np.testing.assert_allclose(forced_lw, lw, atol=1e-10)


def test_sigma_robust_rejects_nan() -> None:
    x = _factor_returns(100, 5, seed=4)
    x[0, 0] = np.nan
    with pytest.raises(engine.OptimizerError, match="NaN"):
        engine.sigma_robust(x)


# ── sigma_robust_pairwise (broad Stage-2 over partially-overlapping funds) ──────


def test_sigma_robust_pairwise_matches_biased_cov_when_fully_observed() -> None:
    """On a fully-observed panel the pairwise estimator equals the biased
    sample covariance (1/n convention), annualized ×252 and PSD-repaired."""
    x = _factor_returns(300, 4, seed=10)
    sigma, kept, excluded = engine.sigma_robust_pairwise(x, min_pair_overlap=50)
    assert kept == [0, 1, 2, 3]
    assert excluded == {}
    expected = engine.repair_psd(np.cov(x, rowvar=False, bias=True) * engine.TRADING_DAYS)
    np.testing.assert_allclose(sigma, expected, atol=1e-9)


def test_sigma_robust_pairwise_tolerates_nan_unlike_sigma_robust() -> None:
    """The differentiator: a matrix with NaN (a young fund's pre-inception
    gap) is accepted — each pair's covariance uses that pair's overlap — and
    yields a symmetric PSD annualized sigma, where sigma_robust would refuse."""
    x = _factor_returns(300, 3, seed=11)
    x[:60, 2] = np.nan  # asset 2 born 60 rows in
    with pytest.raises(engine.OptimizerError, match="NaN"):
        engine.sigma_robust(x)  # baseline refuses NaN
    sigma, kept, excluded = engine.sigma_robust_pairwise(x, min_pair_overlap=100)
    assert kept == [0, 1, 2] and excluded == {}
    assert sigma.shape == (3, 3)
    np.testing.assert_allclose(sigma, sigma.T, atol=1e-12)
    assert np.isfinite(sigma).all()
    assert np.linalg.eigvalsh(sigma).min() > -1e-9  # PSD after repair


def test_sigma_robust_pairwise_excludes_short_overlap_column() -> None:
    """A fund whose median pairwise overlap is below the floor is dropped; the
    covariance is rebuilt on the survivors (reported via kept/excluded)."""
    x = _factor_returns(300, 4, seed=12)
    x[:250, 3] = np.nan  # asset 3 overlaps each other column only 50 rows
    sigma, kept, excluded = engine.sigma_robust_pairwise(x, min_pair_overlap=200)
    assert kept == [0, 1, 2]
    assert set(excluded) == {3}
    assert sigma.shape == (3, 3)
    assert np.linalg.eigvalsh(sigma).min() > -1e-9


def test_sigma_robust_pairwise_raises_when_fewer_than_two_survive() -> None:
    x = _factor_returns(300, 3, seed=13)
    x[:280, 1] = np.nan
    x[:280, 2] = np.nan  # only asset 0 has broad overlap
    with pytest.raises(engine.OptimizerError):
        engine.sigma_robust_pairwise(x, min_pair_overlap=200)
