import numpy as np

from app.optimizer import momentum_view as mv


def _risk_inputs():
    rng = np.random.default_rng(7)
    groups = ["equity", "thematic", "fixed_income", "alternatives"]
    returns = rng.normal(0.0004, 0.01, (600, 4))
    prior = np.array([0.4, 0.1, 0.4, 0.1])
    return returns, groups, prior


def test_multiplier_zero_returns_equilibrium() -> None:
    returns, groups, prior = _risk_inputs()
    mu = mv.category_momentum_mu(
        returns, groups, prior, "risk_on", view_confidence_multiplier=0.0
    )
    pi = mv.category_momentum_mu(
        returns, groups, prior, "risk_off"  # risk_off path already returns pi
    )
    assert np.allclose(mu, pi)


def test_multiplier_one_matches_default() -> None:
    returns, groups, prior = _risk_inputs()
    a = mv.category_momentum_mu(returns, groups, prior, "risk_on")
    b = mv.category_momentum_mu(
        returns, groups, prior, "risk_on", view_confidence_multiplier=1.0
    )
    assert np.allclose(a, b)


def test_half_multiplier_tilts_less_than_full() -> None:
    returns, groups, prior = _risk_inputs()
    pi = mv.category_momentum_mu(
        returns, groups, prior, "risk_on", view_confidence_multiplier=0.0
    )
    full = mv.category_momentum_mu(
        returns, groups, prior, "risk_on", view_confidence_multiplier=1.0
    )
    half = mv.category_momentum_mu(
        returns, groups, prior, "risk_on", view_confidence_multiplier=0.5
    )
    # half-confidence tilt is strictly between equilibrium and full-confidence
    dist_full = float(np.linalg.norm(full - pi))
    dist_half = float(np.linalg.norm(half - pi))
    assert 0.0 < dist_half < dist_full


def test_multiplier_never_passes_zero_confidence(monkeypatch) -> None:
    returns, groups, prior = _risk_inputs()
    seen: list[list[float]] = []
    real = mv.bl.omega_idzorek

    def spy(p, sigma, confidences, tau):
        seen.append(list(confidences))
        return real(p, sigma, confidences, tau=tau)

    monkeypatch.setattr(mv.bl, "omega_idzorek", spy)
    mv.category_momentum_mu(
        returns, groups, prior, "risk_on", view_confidence_multiplier=0.5
    )
    assert seen and all(0.0 < c <= 1.0 for conf in seen for c in conf)
