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


# ── T2C-1: per-asset bound vectors + block budgets ──────────────────────────


def test_bounds_constraints_per_asset_vectors_bind() -> None:
    import cvxpy as cp

    # Asset 0 capped at 0.10, others free up to 1; min 0.05 on asset 2.
    n = 3
    w = cp.Variable(n)
    caps = np.array([0.10, 1.0, 1.0])
    mins = np.array([0.0, 0.0, 0.05])
    cons = engine.bounds_constraints(w, cap_vec=caps, min_vec=mins, blocks=None)
    sigma = np.diag([0.01, 0.04, 0.09])
    prob = cp.Problem(cp.Minimize(cp.quad_form(w, cp.psd_wrap(sigma))), cons)
    prob.solve()
    assert str(prob.status) == cp.OPTIMAL
    weights = np.asarray(w.value).ravel()
    assert abs(weights.sum() - 1.0) < 1e-6
    assert weights[0] <= 0.10 + 1e-6
    assert weights[2] >= 0.05 - 1e-6


def test_bounds_constraints_block_budget_caps_group_sum() -> None:
    import cvxpy as cp

    # Two blocks: {0,1} must sum to <= 0.30; {2,3} sum in [0.40, 1.0].
    n = 4
    w = cp.Variable(n)
    blocks = [
        engine.BlockBudget(indices=[0, 1], lo=0.0, hi=0.30),
        engine.BlockBudget(indices=[2, 3], lo=0.40, hi=1.0),
    ]
    cons = engine.bounds_constraints(w, cap_vec=None, min_vec=None, blocks=blocks)
    sigma = np.diag([0.01, 0.01, 0.04, 0.04])
    prob = cp.Problem(cp.Minimize(cp.quad_form(w, cp.psd_wrap(sigma))), cons)
    prob.solve()
    assert str(prob.status) == cp.OPTIMAL
    weights = np.asarray(w.value).ravel()
    assert weights[0] + weights[1] <= 0.30 + 1e-6
    assert weights[2] + weights[3] >= 0.40 - 1e-6


def test_bounds_constraints_block_floor_infeasible_against_caps_fails_loud() -> None:
    import cvxpy as cp

    # Block {0,1} floor 0.80, but each asset capped at 0.30 -> max group sum 0.60
    # < 0.80: structurally infeasible, must fail loud BEFORE solving.
    w = cp.Variable(4)
    caps = np.array([0.30, 0.30, 1.0, 1.0])
    blocks = [engine.BlockBudget(indices=[0, 1], lo=0.80, hi=1.0)]
    with pytest.raises(engine.OptimizerError, match="block floor"):
        engine.bounds_constraints(w, cap_vec=caps, min_vec=None, blocks=blocks)


def test_bounds_constraints_block_sum_of_floors_exceeds_one_fails_loud() -> None:
    import cvxpy as cp

    # Two disjoint blocks whose floors sum to > 1 can never satisfy sum(w)=1.
    w = cp.Variable(4)
    blocks = [
        engine.BlockBudget(indices=[0, 1], lo=0.60, hi=1.0),
        engine.BlockBudget(indices=[2, 3], lo=0.60, hi=1.0),
    ]
    with pytest.raises(engine.OptimizerError, match="block floors"):
        engine.bounds_constraints(w, cap_vec=None, min_vec=None, blocks=blocks)


def test_bounds_constraints_empty_block_indices_fails_loud() -> None:
    import cvxpy as cp

    w = cp.Variable(3)
    blocks = [engine.BlockBudget(indices=[], lo=0.0, hi=0.5)]
    with pytest.raises(engine.OptimizerError, match="empty"):
        engine.bounds_constraints(w, cap_vec=None, min_vec=None, blocks=blocks)


# ── T2C-2: solve_min_cvar honours the bounds bundle ─────────────────────────


def test_min_cvar_with_bounds_block_budget_binds() -> None:
    scenarios = _random_scenarios(t=500, n=4)
    blocks = [engine.BlockBudget(indices=[0, 1], lo=0.0, hi=0.20)]
    weights, status = engine.solve_min_cvar(
        scenarios,
        cap=None,
        bounds=engine.BoundsBundle(cap_vec=None, min_vec=None, blocks=blocks),
    )
    _assert_valid(weights, status)
    assert weights[0] + weights[1] <= 0.20 + 1e-6


# ── T2C-3: L1 turnover penalty ──────────────────────────────────────────────


def test_min_cvar_turnover_penalty_pulls_toward_current() -> None:
    scenarios = _random_scenarios(t=600, n=4, seed=7)
    current = np.array([0.25, 0.25, 0.25, 0.25])
    w_free, _ = engine.solve_min_cvar(scenarios, cap=None)
    w_sticky, status = engine.solve_min_cvar(
        scenarios, cap=None, current_weights=current, turnover_lambda=5.0
    )
    _assert_valid(w_sticky, status)
    assert np.abs(w_sticky - current).sum() < np.abs(w_free - current).sum()


def test_min_cvar_turnover_zero_lambda_matches_unpenalized() -> None:
    scenarios = _random_scenarios(t=600, n=4, seed=7)
    current = np.array([0.10, 0.20, 0.30, 0.40])
    w0, _ = engine.solve_min_cvar(scenarios, cap=None)
    w1, _ = engine.solve_min_cvar(
        scenarios, cap=None, current_weights=current, turnover_lambda=0.0
    )
    np.testing.assert_allclose(w0, w1, atol=1e-4)


def test_min_cvar_turnover_requires_current_weights() -> None:
    scenarios = _random_scenarios(t=200, n=3)
    with pytest.raises(engine.OptimizerError, match="turnover_lambda requires"):
        engine.solve_min_cvar(scenarios, turnover_lambda=1.0)


def test_min_cvar_turnover_current_weights_shape_checked() -> None:
    scenarios = _random_scenarios(t=200, n=3)
    with pytest.raises(engine.OptimizerError, match="current_weights"):
        engine.solve_min_cvar(
            scenarios, current_weights=np.array([0.5, 0.5]), turnover_lambda=1.0
        )


# ── T2C-5: CVaR-as-constraint max-return ────────────────────────────────────


def _mu_and_scenarios(n: int = 4, t: int = 600, seed: int = 3):
    rng = np.random.default_rng(seed)
    vols = np.array([0.010, 0.012, 0.020, 0.030])[:n]
    scen = rng.normal(0.0, 1.0, size=(t, n)) * vols
    mu = np.array([0.04, 0.06, 0.10, 0.14])[:n]
    return mu, scen


def test_max_return_cvar_capped_optimal_and_caps() -> None:
    mu, scen = _mu_and_scenarios()
    w, status = engine.solve_max_return_cvar_capped(
        scen, mu=mu, cvar_limit=0.05, alpha=0.95, cap=0.5
    )
    _assert_valid(w, status, cap=0.5)


def test_max_return_cvar_capped_tighter_limit_lowers_return() -> None:
    mu, scen = _mu_and_scenarios()
    w_loose, _ = engine.solve_max_return_cvar_capped(
        scen, mu=mu, cvar_limit=0.08, alpha=0.95, cap=None
    )
    w_tight, _ = engine.solve_max_return_cvar_capped(
        scen, mu=mu, cvar_limit=0.025, alpha=0.95, cap=None
    )
    assert float(mu @ w_tight) <= float(mu @ w_loose) + 1e-6


def test_max_return_cvar_capped_realized_cvar_within_limit() -> None:
    mu, scen = _mu_and_scenarios()
    limit = 0.03
    w, _ = engine.solve_max_return_cvar_capped(
        scen, mu=mu, cvar_limit=limit, alpha=0.95, cap=None
    )
    realized = engine._realized_cvar(w, scen, alpha=0.95)
    assert realized <= limit + 1e-4


def test_max_return_cvar_capped_requires_mu() -> None:
    _, scen = _mu_and_scenarios()
    with pytest.raises(engine.OptimizerError, match="mu"):
        engine.solve_max_return_cvar_capped(scen, mu=None, cvar_limit=0.05)  # type: ignore[arg-type]


def test_max_return_cvar_capped_rejects_nonpositive_limit() -> None:
    mu, scen = _mu_and_scenarios()
    with pytest.raises(engine.OptimizerError, match="cvar_limit"):
        engine.solve_max_return_cvar_capped(scen, mu=mu, cvar_limit=0.0)


def test_max_return_cvar_capped_with_bounds_bundle_binds() -> None:
    """Engine-side dispatch: BoundsBundle path is exercised end-to-end."""
    mu, scen = _mu_and_scenarios(n=4, t=600)
    blocks = [engine.BlockBudget(indices=[2, 3], lo=0.0, hi=0.30)]
    bundle = engine.BoundsBundle(
        cap_vec=np.array([0.50, 0.50, 0.30, 0.30]),
        min_vec=None,
        blocks=blocks,
    )
    w, status = engine.solve_max_return_cvar_capped(
        scen, mu=mu, cvar_limit=0.05, alpha=0.95, bounds=bundle
    )
    _assert_valid(w, status)
    # Block budget must bind: assets 2+3 ≤ 0.30.
    assert w[2] + w[3] <= 0.30 + 1e-6


def test_max_return_cvar_capped_rejects_nan_mu() -> None:
    """NaN in the BL posterior mu must raise a clear OptimizerError."""
    _, scen = _mu_and_scenarios()
    mu_bad = np.array([0.04, np.nan, 0.10, 0.14])
    with pytest.raises(engine.OptimizerError, match="NaN"):
        engine.solve_max_return_cvar_capped(scen, mu=mu_bad, cvar_limit=0.05)


# ── T3F-2: SCS fallback + post-solve re-verification + telemetry ──────────────

from app.optimizer.engine import SolveTelemetry, _finalize, _verify_constraints


def test_finalize_telemetry_records_solver_and_realized_constraints() -> None:
    import cvxpy as cp

    sigma = np.diag([0.04, 0.09, 0.16])
    w = cp.Variable(3)
    problem = cp.Problem(
        cp.Minimize(cp.quad_form(w, cp.psd_wrap(sigma))),
        engine.base_constraints(w, cap=0.5, min_weight=None),
    )
    weights, status, telemetry = _finalize(
        problem, w, "tele", cap=0.5, min_weight=None, with_telemetry=True
    )
    assert status == "optimal"
    assert isinstance(telemetry, SolveTelemetry)
    assert telemetry.solver in {"CLARABEL", "SCS"}
    assert telemetry.used_fallback in {True, False}
    assert telemetry.realized_max_weight <= 0.5 + 1e-6
    assert abs(telemetry.realized_sum - 1.0) < 1e-6


def test_finalize_default_signature_still_returns_two_tuple() -> None:
    """Back-compat: without with_telemetry, _finalize returns (weights, status)."""
    import cvxpy as cp

    sigma = np.diag([0.04, 0.09])
    w = cp.Variable(2)
    problem = cp.Problem(
        cp.Minimize(cp.quad_form(w, cp.psd_wrap(sigma))),
        engine.base_constraints(w, cap=None, min_weight=None),
    )
    result = _finalize(problem, w, "compat", cap=None, min_weight=None)
    assert isinstance(result, tuple) and len(result) == 2
    weights, status = result
    _assert_valid(weights, status)


def test_verify_constraints_rejects_cap_violation() -> None:
    weights = np.array([0.6, 0.4])
    ok, reason = _verify_constraints(weights, cap=0.5, min_weight=None)
    assert ok is False
    assert "cap" in reason


def test_verify_constraints_rejects_sum_violation() -> None:
    weights = np.array([0.5, 0.4])  # sums to 0.9
    ok, reason = _verify_constraints(weights, cap=None, min_weight=None)
    assert ok is False
    assert "sum" in reason


def test_verify_constraints_rejects_min_weight_violation() -> None:
    weights = np.array([0.95, 0.05])
    ok, reason = _verify_constraints(weights, cap=None, min_weight=0.1)
    assert ok is False
    assert "min_weight" in reason


def test_verify_constraints_accepts_valid() -> None:
    weights = np.array([0.5, 0.5])
    ok, reason = _verify_constraints(weights, cap=0.6, min_weight=0.1)
    assert ok is True
    assert reason == ""


def test_solve_min_vol_still_passes_post_verification() -> None:
    """The public solver path now runs post-solve re-verification internally;
    a normal solve must still succeed and respect the cap."""
    sigma = np.diag([0.05**2, 0.2**2, 0.2**2, 0.2**2, 0.2**2])
    weights, status = engine.solve_min_vol(sigma, cap=0.25)
    _assert_valid(weights, status, cap=0.25)
