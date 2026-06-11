"""Engine gates (dispatch F8 §4):

- G2 — analytic optimizer checks: iid 50/50, 1:2 vols min-vol closed form,
  diagonal-Σ ERC ∝ 1/σ, solver 'optimal', sum=1 (1e-6), caps respected.
- G4 — Ledoit-Wolf shrinkage == sklearn reference (atol 1e-10).
- G5 — anti-μ guard: no engine objective accepts a historical-mean input;
  structural check that no mean is estimated inside engine/data.
"""

import inspect
import pathlib

import numpy as np
import pytest

from app.optimizer import engine

_SUM_ATOL = 1e-6


def _assert_valid(weights: np.ndarray, status: str, cap: float | None = None) -> None:
    assert status == "optimal"
    assert abs(float(weights.sum()) - 1.0) < _SUM_ATOL
    assert (weights >= -_SUM_ATOL).all()
    if cap is not None:
        assert (weights <= cap + 1e-6).all()


# ── G2: analytic checks ──────────────────────────────────────────────────────


def test_g2_iid_two_assets_min_vol_is_50_50() -> None:
    sigma = np.array([[0.04, 0.0], [0.0, 0.04]])
    weights, status = engine.solve_min_vol(sigma, cap=None)
    _assert_valid(weights, status)
    np.testing.assert_allclose(weights, [0.5, 0.5], atol=1e-3)


def test_g2_iid_two_assets_erc_is_50_50() -> None:
    sigma = np.array([[0.04, 0.0], [0.0, 0.04]])
    weights, status = engine.solve_erc(sigma, cap=None)
    _assert_valid(weights, status)
    np.testing.assert_allclose(weights, [0.5, 0.5], atol=1e-3)


def test_g2_min_vol_uncorrelated_vols_1_to_2_closed_form() -> None:
    # σ = (0.1, 0.2) uncorrelated ⇒ w ∝ 1/σ² ⇒ [0.8, 0.2].
    sigma = np.diag([0.1**2, 0.2**2])
    weights, status = engine.solve_min_vol(sigma, cap=None)
    _assert_valid(weights, status)
    np.testing.assert_allclose(weights, [0.8, 0.2], atol=1e-3)


def test_g2_erc_diagonal_sigma_weights_proportional_to_inverse_vol() -> None:
    vols = np.array([0.1, 0.2, 0.4])
    sigma = np.diag(vols**2)
    weights, status = engine.solve_erc(sigma, cap=None)
    _assert_valid(weights, status)
    expected = (1 / vols) / (1 / vols).sum()
    np.testing.assert_allclose(weights, expected, atol=1e-3)


def test_g2_equal_weight() -> None:
    weights, status = engine.solve_equal_weight(5)
    _assert_valid(weights, status, cap=0.25)
    np.testing.assert_allclose(weights, np.full(5, 0.2), atol=1e-12)


def test_g2_equal_weight_infeasible_cap_fails_loud() -> None:
    with pytest.raises(engine.OptimizerError, match="infeasible"):
        engine.solve_equal_weight(2, cap=0.25)


def _random_scenarios(t: int = 500, n: int = 5, seed: int = 42) -> np.ndarray:
    rng = np.random.default_rng(seed)
    cov = np.diag([0.01, 0.012, 0.009, 0.015, 0.011]) ** 2
    return rng.multivariate_normal(np.zeros(n), cov[:n, :n], size=t)


def test_g2_min_cvar_optimal_sum_and_caps() -> None:
    scenarios = _random_scenarios()
    weights, status = engine.solve_min_cvar(scenarios, cap=0.3)
    _assert_valid(weights, status, cap=0.3)


def test_g2_min_vol_caps_respected() -> None:
    sigma = np.diag([0.05**2, 0.2**2, 0.2**2, 0.2**2, 0.2**2])
    weights, status = engine.solve_min_vol(sigma, cap=0.25)
    _assert_valid(weights, status, cap=0.25)
    # The low-vol asset would dominate without the cap — the cap must bind.
    assert weights[0] == pytest.approx(0.25, abs=1e-4)


def test_g2_max_diversification_optimal_and_caps() -> None:
    sigma = np.array(
        [
            [0.04, 0.006, 0.0],
            [0.006, 0.09, 0.0],
            [0.0, 0.0, 0.0225],
        ]
    )
    weights, status = engine.solve_max_diversification(sigma, cap=0.6)
    _assert_valid(weights, status, cap=0.6)


def test_g2_min_weight_respected() -> None:
    sigma = np.diag([0.05**2, 0.2**2, 0.3**2])
    weights, status = engine.solve_min_vol(sigma, cap=None, min_weight=0.1)
    _assert_valid(weights, status)
    assert (weights >= 0.1 - 1e-6).all()


# ── G4: Ledoit-Wolf == sklearn reference ─────────────────────────────────────


def test_g4_ledoit_wolf_matches_sklearn_reference() -> None:
    from sklearn.covariance import LedoitWolf

    rng = np.random.default_rng(123)
    returns = rng.normal(0.0002, 0.01, size=(300, 5))
    ours = engine.sigma_ledoit_wolf(returns)
    reference = LedoitWolf().fit(returns).covariance_ * 252
    np.testing.assert_allclose(ours, (reference + reference.T) / 2, atol=1e-10)


def test_g4_sigma_rejects_nan() -> None:
    returns = np.full((50, 2), 0.01)
    returns[3, 1] = np.nan
    with pytest.raises(engine.OptimizerError, match="NaN"):
        engine.sigma_ledoit_wolf(returns)


# ── G5: anti-μ guard ─────────────────────────────────────────────────────────


def test_g5_mu_free_solvers_accept_no_mu_parameter() -> None:
    for func in (
        engine.solve_equal_weight,
        engine.solve_min_vol,
        engine.solve_erc,
        engine.solve_max_diversification,
    ):
        params = inspect.signature(func).parameters
        assert "mu" not in params, f"{func.__name__} must not accept expected returns"
        assert "ret_floor" not in params


def test_g5_min_cvar_floor_requires_explicit_mu() -> None:
    scenarios = _random_scenarios(t=100, n=3)[:, :3]
    with pytest.raises(engine.OptimizerError, match="ret_floor requires an explicit mu"):
        engine.solve_min_cvar(scenarios, cap=None, ret_floor=0.05)


def test_g5_structural_no_mean_estimation_in_engine_or_data() -> None:
    """Neither engine.py nor data.py may estimate a mean of returns; the only
    sanctioned historical-mean estimator is black_litterman.historical_mean_ann
    (used exclusively for scenario re-centering)."""
    package = pathlib.Path(engine.__file__).parent
    for name in ("engine.py", "data.py"):
        source = (package / name).read_text(encoding="utf-8")
        assert ".mean(" not in source, f"{name} estimates a mean — gate G5 violation"
        assert "np.average" not in source

    bl_source = (package / "black_litterman.py").read_text(encoding="utf-8")
    assert bl_source.count(".mean(") == 1, (
        "black_litterman.py must contain exactly one mean estimation "
        "(historical_mean_ann, for re-centering only)"
    )
