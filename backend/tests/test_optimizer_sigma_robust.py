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
