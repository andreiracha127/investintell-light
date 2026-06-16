"""PSD eigenvalue-floor repair (rank 40) — ported from legacy
assemble_factor_covariance conditioning (factor_model_service.py:706-723)."""

import numpy as np
import pytest

from app.optimizer import engine


def _symmetrize(m: np.ndarray) -> np.ndarray:
    return (m + m.T) / 2.0


def test_repair_psd_floors_negative_eigenvalues() -> None:
    # Construct a symmetric matrix with one negative eigenvalue.
    q, _ = np.linalg.qr(np.random.default_rng(0).standard_normal((3, 3)))
    sigma = q @ np.diag([1.0, 0.5, -0.2]) @ q.T
    sigma = _symmetrize(sigma)
    repaired = engine.repair_psd(sigma, kappa_target=1e4)
    eigvals = np.linalg.eigvalsh(repaired)
    # All eigenvalues are now >= 0 (floored at max_eigval / kappa_target).
    assert eigvals.min() >= 0.0
    assert np.allclose(repaired, repaired.T, atol=1e-12)


def test_repair_psd_enforces_conditioning_band() -> None:
    # Pathological conditioning: kappa = 1e8, far above target 1e4.
    sigma = np.diag([1.0, 1e-8, 1e-8])
    repaired = engine.repair_psd(sigma, kappa_target=1e4)
    eigvals = np.linalg.eigvalsh(repaired)
    kappa = float(eigvals.max() / eigvals.min())
    assert kappa <= 1e4 + 1.0  # floored to max_eigval / kappa_target


def test_repair_psd_leaves_well_conditioned_matrix_unchanged() -> None:
    sigma = np.diag([0.04, 0.03, 0.05])
    repaired = engine.repair_psd(sigma, kappa_target=1e4)
    np.testing.assert_allclose(repaired, sigma, atol=1e-12)


def test_repair_psd_rejects_non_square() -> None:
    with pytest.raises(engine.OptimizerError, match="square"):
        engine.repair_psd(np.zeros((2, 3)))


def test_repair_psd_rejects_nan() -> None:
    sigma = np.array([[1.0, np.nan], [np.nan, 1.0]])
    with pytest.raises(engine.OptimizerError, match="NaN/inf"):
        engine.repair_psd(sigma)


def test_repair_psd_invalid_kappa_target() -> None:
    with pytest.raises(engine.OptimizerError, match="kappa_target"):
        engine.repair_psd(np.diag([1.0, 1.0]), kappa_target=0.5)
