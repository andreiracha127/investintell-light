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
