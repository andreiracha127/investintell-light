"""BL Woodbury / full-Ω multi-view posterior (rank 43)."""

import numpy as np
import pytest

from app.optimizer import black_litterman as bl


def _fixture_sigma() -> np.ndarray:
    vols = np.array([0.10, 0.15, 0.20])
    corr = np.array([[1.0, 0.3, 0.2], [0.3, 1.0, 0.25], [0.2, 0.25, 1.0]])
    return corr * np.outer(vols, vols)


_W_MKT = np.array([0.5, 0.3, 0.2])


def test_woodbury_matches_classic_posterior_diagonal_omega() -> None:
    # With a diagonal, well-conditioned Omega, Woodbury == classic inverse form.
    sigma = _fixture_sigma()
    pi = bl.equilibrium(sigma, _W_MKT)
    views = [bl.AbsoluteView(asset=0, q=0.12, confidence=0.6)]
    p, q = bl.build_view_matrices(views, 3)
    omega = bl.omega_idzorek(p, sigma, [0.6])
    mu_classic, _ = bl.posterior(sigma, pi, p, q, omega)
    mu_wood = bl.posterior_woodbury(sigma, pi, p, q, omega)
    np.testing.assert_allclose(mu_classic, mu_wood, atol=1e-9)


def test_woodbury_supports_full_offdiagonal_omega() -> None:
    # Two correlated views with a non-diagonal Omega (off-diag != 0).
    sigma = _fixture_sigma()
    pi = bl.equilibrium(sigma, _W_MKT)
    p = np.array([[1.0, 0.0, 0.0], [0.0, 1.0, 0.0]])
    q = np.array([0.12, 0.09])
    omega = np.array([[4e-4, 1e-4], [1e-4, 5e-4]])  # PSD, off-diagonal
    mu = bl.posterior_woodbury(sigma, pi, p, q, omega)
    assert mu.shape == (3,)
    assert np.all(np.isfinite(mu))
    # Bullish absolute view on asset 0 raises its posterior above equilibrium.
    assert mu[0] > pi[0]


def test_woodbury_zero_variance_asset_does_not_blow_up() -> None:
    # Asset 2 has zero variance (flat NAV) -> its row of tauSigma*P^T is zero;
    # the Woodbury form must still produce finite output (classic inv(tauSigma)
    # would be singular).
    sigma = _fixture_sigma()
    sigma[2, :] = 0.0
    sigma[:, 2] = 0.0
    sigma = (sigma + sigma.T) / 2.0
    pi = np.array([0.05, 0.06, 0.0])
    views = [bl.AbsoluteView(asset=0, q=0.12, confidence=0.6)]
    p, q = bl.build_view_matrices(views, 3)
    omega = np.diag([4e-4])
    mu = bl.posterior_woodbury(sigma, pi, p, q, omega)
    assert np.all(np.isfinite(mu))


def test_woodbury_rejects_non_psd_omega() -> None:
    sigma = _fixture_sigma()
    pi = bl.equilibrium(sigma, _W_MKT)
    p = np.array([[1.0, 0.0, 0.0]])
    q = np.array([0.12])
    omega = np.array([[-1e-4]])  # negative -> not PSD
    with pytest.raises(ValueError, match="PSD|positive"):
        bl.posterior_woodbury(sigma, pi, p, q, omega)


def test_woodbury_rejects_shape_mismatch() -> None:
    sigma = _fixture_sigma()
    pi = bl.equilibrium(sigma, _W_MKT)
    p = np.array([[1.0, 0.0, 0.0]])
    q = np.array([0.12, 0.09])  # 2 entries but P has 1 row
    omega = np.diag([4e-4])
    with pytest.raises(ValueError, match="inconsistent|shape|rows"):
        bl.posterior_woodbury(sigma, pi, p, q, omega)
