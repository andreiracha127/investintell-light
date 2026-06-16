"""Regime-adjusted CVaR limit (rank 37)."""

import numpy as np
import pytest

from app.optimizer import engine


def _scenarios(t: int = 600, n: int = 4, seed: int = 11) -> np.ndarray:
    rng = np.random.default_rng(seed)
    cov = np.diag([0.01, 0.012, 0.02, 0.03]) ** 2
    return rng.multivariate_normal(np.zeros(n), cov[:n, :n], size=t)


def test_regime_multiplier_tightens_limit_in_stress() -> None:
    # base limit 0.10 (10% loss); stress multiplier 0.5 tightens to 0.05.
    adjusted = engine.compute_regime_adjusted_limit(0.10, 0.5)
    assert adjusted == pytest.approx(0.05)


def test_regime_multiplier_loosens_limit_in_calm() -> None:
    adjusted = engine.compute_regime_adjusted_limit(0.10, 1.5)
    assert adjusted == pytest.approx(0.15)


def test_regime_multiplier_rejects_nonpositive_base() -> None:
    with pytest.raises(engine.OptimizerError, match="base_limit"):
        engine.compute_regime_adjusted_limit(0.0, 1.0)


def test_regime_multiplier_rejects_nonpositive_multiplier() -> None:
    with pytest.raises(engine.OptimizerError, match="regime_multiplier"):
        engine.compute_regime_adjusted_limit(0.10, 0.0)


def test_min_cvar_with_generous_limit_is_feasible() -> None:
    scenarios = _scenarios()
    weights, status = engine.solve_min_cvar(scenarios, cvar_limit=0.50)
    assert status == "optimal"
    assert abs(float(weights.sum()) - 1.0) < 1e-6


def test_min_cvar_with_impossible_limit_fails_loud() -> None:
    # An absurdly tight CVaR limit (0.0001) is infeasible -> OptimizerError.
    scenarios = _scenarios()
    with pytest.raises(engine.OptimizerError):
        engine.solve_min_cvar(scenarios, cvar_limit=0.0001)


def test_min_cvar_rejects_nonpositive_cvar_limit() -> None:
    scenarios = _scenarios()
    with pytest.raises(engine.OptimizerError, match="cvar_limit"):
        engine.solve_min_cvar(scenarios, cvar_limit=0.0)
