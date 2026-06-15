"""T2C-7/T2C-8 — regime-conditional CVaR limit multiplier."""

import pytest

from app.services import portfolio_builder as pb


def test_multiplier_risk_off_tightens_limit() -> None:
    assert pb.regime_cvar_multiplier("risk_off", risk_off_factor=0.5) == 0.5


def test_multiplier_risk_on_is_neutral() -> None:
    assert pb.regime_cvar_multiplier("risk_on", risk_off_factor=0.5) == 1.0


def test_multiplier_unknown_state_is_neutral() -> None:
    assert pb.regime_cvar_multiplier(None, risk_off_factor=0.5) == 1.0
    assert pb.regime_cvar_multiplier("something_else", risk_off_factor=0.5) == 1.0


def test_multiplier_rejects_nonpositive_factor() -> None:
    with pytest.raises(ValueError, match="risk_off_factor"):
        pb.regime_cvar_multiplier("risk_off", risk_off_factor=0.0)


def test_apply_regime_to_limit_tightens() -> None:
    assert pb.apply_regime_cvar_limit(0.10, "risk_off", risk_off_factor=0.5) == pytest.approx(0.05)
    assert pb.apply_regime_cvar_limit(0.10, "risk_on", risk_off_factor=0.5) == pytest.approx(0.10)
