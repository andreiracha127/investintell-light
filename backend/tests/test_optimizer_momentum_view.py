"""COMBO S2: category-level momentum view service (port of harness `_category_mu`).

The regime_aware Level-1 mu = equilibrium π plus ONE relative top-minus-bottom
12-1 momentum view over the RISK categories, subordinate to the live gate. Causal
(the 12-1 score skips the most recent month) and degrade-safe (too few risk
categories / risk_off gate / use_views=False -> equilibrium only).
"""

import numpy as np
import pytest

from app.optimizer import black_litterman as bl
from app.optimizer import engine
from app.optimizer import momentum_view as mv
from app.optimizer.mandate import DELTA_MARKET

_GROUPS = ["equity", "thematic", "fixed_income", "alternatives", "cash"]


def _returns_with_momentum(seed: int = 11, t: int = 600) -> np.ndarray:
    """5 proxies (4 risk + cash). Equity has a strong positive trailing drift and
    fixed_income a negative one (in the 12-1 window), the rest ~flat."""
    rng = np.random.default_rng(seed)
    n = len(_GROUPS)
    base = rng.normal(0.0, 0.01, size=(t, n))
    # drift over the 12-1 window only (skip the most recent ~21 days)
    drift = np.zeros(n)
    drift[0] = +0.0015   # equity winner
    drift[2] = -0.0015   # fixed_income loser
    base[: t - 21] += drift
    return base


def _equilibrium(returns: np.ndarray, prior: np.ndarray) -> np.ndarray:
    win = np.nan_to_num(returns[-504:], nan=0.0)
    sigma = engine.sigma_ledoit_wolf(win)
    return bl.equilibrium(sigma, prior, delta=DELTA_MARKET)


def _flat_prior(n: int) -> np.ndarray:
    return np.full(n, 1.0 / n)


def test_momentum_score_skips_recent_month() -> None:
    # 12-1 momentum must ignore the most recent MOM_SKIP days.
    rng = np.random.default_rng(3)
    r = rng.normal(0.0, 0.01, size=(400, 3))
    base = mv._momentum_score(r, [0, 1, 2])
    r2 = r.copy()
    r2[-mv.MOM_SKIP:, 0] += 0.5  # huge spike in the skipped tail of col 0
    after = mv._momentum_score(r2, [0, 1, 2])
    assert np.allclose(base, after)


def test_momentum_mu_tilts_toward_winners() -> None:
    r = _returns_with_momentum()
    prior = _flat_prior(len(_GROUPS))
    pi = _equilibrium(r, prior)
    mu = mv.category_momentum_mu(r, _GROUPS, prior, gate_state="risk_on")
    # The high-momentum equity proxy is tilted UP vs equilibrium more than the
    # low-momentum fixed_income proxy (relative top-minus-bottom view).
    assert (mu[0] - pi[0]) > (mu[2] - pi[2])
    assert not np.allclose(mu, pi)


def test_momentum_mu_risk_off_is_equilibrium() -> None:
    r = _returns_with_momentum()
    prior = _flat_prior(len(_GROUPS))
    pi = _equilibrium(r, prior)
    mu = mv.category_momentum_mu(r, _GROUPS, prior, gate_state="risk_off")
    assert np.allclose(mu, pi)


def test_momentum_mu_use_views_false_is_equilibrium() -> None:
    r = _returns_with_momentum()
    prior = _flat_prior(len(_GROUPS))
    pi = _equilibrium(r, prior)
    mu = mv.category_momentum_mu(r, _GROUPS, prior, gate_state="risk_on", use_views=False)
    assert np.allclose(mu, pi)


def test_momentum_mu_too_few_risk_categories_is_equilibrium() -> None:
    # Only 2 risk categories (< MIN_RISK) -> no cross-sectional view.
    groups = ["equity", "fixed_income", "cash", "gold"]
    rng = np.random.default_rng(5)
    r = rng.normal(0.0, 0.01, size=(600, len(groups)))
    prior = _flat_prior(len(groups))
    pi = _equilibrium(r, prior)
    mu = mv.category_momentum_mu(r, groups, prior, gate_state="risk_on")
    assert np.allclose(mu, pi)


def test_momentum_mu_rejects_shape_mismatch() -> None:
    r = _returns_with_momentum()
    with pytest.raises(ValueError, match="match"):
        mv.category_momentum_mu(r, _GROUPS[:-1], _flat_prior(len(_GROUPS)), gate_state="risk_on")
