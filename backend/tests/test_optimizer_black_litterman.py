"""Black-Litterman gates (dispatch F8 §4 G6):

(i)   zero views ⇒ bl_utility weights ≈ w_mkt (atol 0.02, no caps binding);
(ii)  absolute bullish view on X ⇒ μ_X posterior > π_X and weight of X rises;
(iii) relative view tilts the long-short spread;
(iv)  rank-deficient P ⇒ ValueError;
(v)   higher confidence ⇒ stronger tilt (monotonic over 3 points).

Plus unit checks for market_weights (fail-loud on missing AUM), Ω scaling and
scenario re-centering.
"""

import numpy as np
import pytest

from app.optimizer import black_litterman as bl


def _fixture_sigma() -> np.ndarray:
    vols = np.array([0.10, 0.15, 0.20])
    corr = np.array(
        [
            [1.0, 0.3, 0.2],
            [0.3, 1.0, 0.25],
            [0.2, 0.25, 1.0],
        ]
    )
    return corr * np.outer(vols, vols)


_W_MKT = np.array([0.5, 0.3, 0.2])


def _posterior_for(
    views: list[bl.View], confidences: list[float]
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    sigma = _fixture_sigma()
    pi = bl.equilibrium(sigma, _W_MKT)
    p, q = bl.build_view_matrices(views, 3)
    omega = bl.omega_idzorek(p, sigma, confidences)
    mu_bl, sigma_bl = bl.posterior(sigma, pi, p, q, omega)
    return pi, mu_bl, sigma_bl


# ── G6 (i): zero views ⇒ market weights ──────────────────────────────────────


def test_g6_zero_views_bl_utility_recovers_market_weights() -> None:
    sigma = _fixture_sigma()
    pi = bl.equilibrium(sigma, _W_MKT, delta=2.5)
    weights, status = bl.solve_bl_utility(pi, sigma, delta=2.5, cap=None)
    assert status == "optimal"
    np.testing.assert_allclose(weights, _W_MKT, atol=0.02)


# ── G6 (ii): absolute bullish view ───────────────────────────────────────────


def test_g6_absolute_view_raises_posterior_mu_and_weight() -> None:
    sigma = _fixture_sigma()
    pi = bl.equilibrium(sigma, _W_MKT)
    baseline, _ = bl.solve_bl_utility(pi, sigma, cap=None)

    view = bl.AbsoluteView(asset=2, q=float(pi[2]) + 0.06, confidence=0.5)
    _, mu_bl, _ = _posterior_for([view], [0.5])
    assert mu_bl[2] > pi[2]

    tilted, status = bl.solve_bl_utility(mu_bl, sigma, cap=None)
    assert status == "optimal"
    assert tilted[2] > baseline[2]


# ── G6 (iii): relative view tilts the spread ─────────────────────────────────


def test_g6_relative_view_tilts_spread() -> None:
    sigma = _fixture_sigma()
    pi = bl.equilibrium(sigma, _W_MKT)
    baseline, _ = bl.solve_bl_utility(pi, sigma, cap=None)

    view = bl.RelativeView(long=0, short=1, q=float(pi[0] - pi[1]) + 0.05, confidence=0.5)
    _, mu_bl, _ = _posterior_for([view], [0.5])
    assert (mu_bl[0] - mu_bl[1]) > (pi[0] - pi[1])

    tilted, _ = bl.solve_bl_utility(mu_bl, sigma, cap=None)
    assert (tilted[0] - tilted[1]) > (baseline[0] - baseline[1])


# ── G6 (iv): rank-deficient P ────────────────────────────────────────────────


def test_g6_rank_deficient_views_rejected() -> None:
    views: list[bl.View] = [
        bl.AbsoluteView(asset=0, q=0.10, confidence=0.5),
        bl.AbsoluteView(asset=0, q=0.12, confidence=0.5),
    ]
    with pytest.raises(ValueError, match="linearmente dependentes"):
        bl.build_view_matrices(views, 3)


def test_g6_rank_deficient_combination_rejected() -> None:
    # absolute(0) − absolute(1) spans relative(0,1): P is rank-deficient.
    views: list[bl.View] = [
        bl.AbsoluteView(asset=0, q=0.10, confidence=0.5),
        bl.AbsoluteView(asset=1, q=0.05, confidence=0.5),
        bl.RelativeView(long=0, short=1, q=0.05, confidence=0.5),
    ]
    with pytest.raises(ValueError, match="linearmente dependentes"):
        bl.build_view_matrices(views, 3)


# ── G6 (v): confidence → tilt monotonicity ───────────────────────────────────


def test_g6_confidence_monotonic_tilt() -> None:
    sigma = _fixture_sigma()
    pi = bl.equilibrium(sigma, _W_MKT)
    baseline, _ = bl.solve_bl_utility(pi, sigma, cap=None)
    q = float(pi[2]) + 0.06

    tilts = []
    for confidence in (0.2, 0.5, 0.9):
        view = bl.AbsoluteView(asset=2, q=q, confidence=confidence)
        _, mu_bl, _ = _posterior_for([view], [confidence])
        weights, _ = bl.solve_bl_utility(mu_bl, sigma, cap=None)
        tilts.append(float(weights[2] - baseline[2]))
    assert tilts[0] < tilts[1] < tilts[2], f"tilt not monotonic in confidence: {tilts}"


def test_omega_scaling_monotonic_in_confidence() -> None:
    sigma = _fixture_sigma()
    p, _q = bl.build_view_matrices([bl.AbsoluteView(asset=1, q=0.1, confidence=0.5)], 3)
    omegas = [
        float(np.diag(bl.omega_idzorek(p, sigma, [c]))[0]) for c in (0.2, 0.5, 0.9, 1.0)
    ]
    assert omegas[0] > omegas[1] > omegas[2] > omegas[3] > 0


# ── Supporting units ─────────────────────────────────────────────────────────


def test_market_weights_normalizes_aum() -> None:
    weights = bl.market_weights([3e9, 1e9], ["a", "b"])
    np.testing.assert_allclose(weights, [0.75, 0.25])


def test_market_weights_fails_loud_listing_missing_aum() -> None:
    with pytest.raises(ValueError, match="fund:b"):
        bl.market_weights([1e9, None], ["fund:a", "fund:b"])


def test_recenter_scenarios_shifts_daily_mean() -> None:
    rng = np.random.default_rng(7)
    scenarios = rng.normal(0.0004, 0.01, size=(500, 2))
    mu_hist = bl.historical_mean_ann(scenarios)
    mu_target = mu_hist + np.array([0.0252, -0.0252])
    shifted = bl.recenter_scenarios(scenarios, mu_hist, mu_target)
    np.testing.assert_allclose(
        bl.historical_mean_ann(shifted), mu_target, atol=1e-12
    )
    # Co-movement preserved: demeaned scenarios identical.
    np.testing.assert_allclose(
        shifted - shifted.mean(axis=0), scenarios - scenarios.mean(axis=0), atol=1e-12
    )


def test_posterior_no_views_limit_keeps_pi_when_omega_huge() -> None:
    """A view with near-zero confidence barely moves the posterior."""
    sigma = _fixture_sigma()
    pi = bl.equilibrium(sigma, _W_MKT)
    p, q = bl.build_view_matrices([bl.AbsoluteView(asset=0, q=0.5, confidence=1e-6)], 3)
    omega = bl.omega_idzorek(p, sigma, [1e-6])
    mu_bl, _ = bl.posterior(sigma, pi, p, q, omega)
    np.testing.assert_allclose(mu_bl, pi, atol=1e-4)


# ── He-Litterman 3-sigma view-consistency warning (T2F-3) ─────────────────────


def test_view_consistency_flags_view_fighting_prior() -> None:
    """A Q far above the prior-implied P*pi (>3 predictive sigma) is flagged."""
    sigma = _fixture_sigma()
    pi = bl.equilibrium(sigma, _W_MKT)
    # Absolute view on asset 2, far above its equilibrium return, very confident
    # (small Omega) -> large z-score.
    p, q = bl.build_view_matrices(
        [bl.AbsoluteView(asset=2, q=float(pi[2]) + 1.0, confidence=0.99)], 3
    )
    omega = bl.omega_idzorek(p, sigma, [0.99])
    result = bl.view_consistency_he_litterman(p, q, pi, omega, sigma, tau=bl.DEFAULT_TAU)
    assert result["inconsistent"] is True
    assert result["n_flagged"] == 1
    assert result["max_z"] > 3.0
    assert result["threshold_sigma"] == 3.0


def test_view_consistency_passes_view_aligned_with_prior() -> None:
    """A Q equal to the prior-implied value is consistent (z=0)."""
    sigma = _fixture_sigma()
    pi = bl.equilibrium(sigma, _W_MKT)
    p, q = bl.build_view_matrices(
        [bl.AbsoluteView(asset=0, q=float(pi[0]), confidence=0.5)], 3
    )
    omega = bl.omega_idzorek(p, sigma, [0.5])
    result = bl.view_consistency_he_litterman(p, q, pi, omega, sigma, tau=bl.DEFAULT_TAU)
    assert result["inconsistent"] is False
    assert result["n_flagged"] == 0
    assert result["max_z"] == pytest.approx(0.0, abs=1e-9)


def test_view_consistency_relative_view_uses_predictive_dispersion() -> None:
    """A modest relative view within ~3 sigma is NOT flagged."""
    sigma = _fixture_sigma()
    pi = bl.equilibrium(sigma, _W_MKT)
    p, q = bl.build_view_matrices(
        [bl.RelativeView(long=0, short=1, q=float(pi[0] - pi[1]) + 0.01, confidence=0.5)],
        3,
    )
    omega = bl.omega_idzorek(p, sigma, [0.5])
    result = bl.view_consistency_he_litterman(p, q, pi, omega, sigma, tau=bl.DEFAULT_TAU)
    assert result["inconsistent"] is False
    assert 0.0 <= result["max_z"] <= 3.0


# ── T3F-3: robust / ellipsoidal mean-uncertainty SOCP ────────────────────────

import pytest as _pytest
from scipy.stats import chi2 as _chi2

from app.optimizer import black_litterman as _bl
from app.optimizer.engine import OptimizerError as _OptErr


def test_kappa_from_chi2_matches_sqrt_ppf() -> None:
    kappa = _bl._kappa_from_chi2(0.95, n=4, uncertainty_level=None)
    assert kappa == _pytest.approx(float(np.sqrt(_chi2.ppf(0.95, 4))), rel=1e-9)


def test_kappa_scales_with_uncertainty_level() -> None:
    base = _bl._kappa_from_chi2(0.95, n=3, uncertainty_level=None)
    half = _bl._kappa_from_chi2(0.95, n=3, uncertainty_level=0.5)
    assert half == _pytest.approx(0.5 * base, rel=1e-9)


def test_solve_bl_robust_returns_valid_weights() -> None:
    mu = np.array([0.10, 0.08, 0.06])
    sigma = np.diag([0.04, 0.06, 0.09])
    weights, status = _bl.solve_bl_robust(mu, sigma, cap=None)
    assert status == "optimal"
    assert abs(float(weights.sum()) - 1.0) < 1e-6
    assert (weights >= -1e-6).all()


def test_solve_bl_robust_more_uncertainty_shrinks_toward_min_vol() -> None:
    """Higher κ penalizes risky concentration; with strong uncertainty the
    robust portfolio is LESS concentrated than the near-zero-κ (pure-μ) tilt."""
    mu = np.array([0.20, 0.05, 0.05])
    sigma = np.diag([0.09, 0.04, 0.04])
    low, _ = _bl.solve_bl_robust(mu, sigma, cap=None, uncertainty_level=0.01)
    high, _ = _bl.solve_bl_robust(mu, sigma, cap=None, uncertainty_level=3.0)
    assert high[0] < low[0]


def test_solve_bl_robust_respects_cap() -> None:
    mu = np.array([0.20, 0.05, 0.05, 0.05])
    sigma = np.diag([0.04, 0.04, 0.04, 0.04])
    weights, status = _bl.solve_bl_robust(mu, sigma, cap=0.4)
    assert status == "optimal"
    assert (weights <= 0.4 + 1e-6).all()


def test_solve_bl_robust_rejects_mu_shape_mismatch() -> None:
    mu = np.array([0.1, 0.1])  # 2 assets
    sigma = np.diag([0.04, 0.04, 0.04])  # 3x3
    with _pytest.raises(_OptErr, match="mu has shape"):
        _bl.solve_bl_robust(mu, sigma, cap=None)


def test_solve_bl_robust_infeasible_cap_reports_loud() -> None:
    mu = np.array([0.1, 0.1])
    sigma = np.diag([0.04, 0.04])
    with _pytest.raises(_OptErr, match="infeasible"):
        _bl.solve_bl_robust(mu, sigma, cap=0.25)  # 0.25*2 < 1


def test_solve_bl_robust_rejects_bad_confidence() -> None:
    mu = np.array([0.1, 0.1])
    sigma = np.diag([0.04, 0.04])
    with _pytest.raises(_OptErr, match="confidence"):
        _bl.solve_bl_robust(mu, sigma, cap=None, confidence=1.5)
