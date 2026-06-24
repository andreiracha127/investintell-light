import pytest

from app.optimizer import gate_overlay as go


def test_shapes_and_profiles_exist() -> None:
    assert isinstance(go.GATE_OVERLAY_SHAPE, go.GateOverlayShape)
    assert set(go.PROFILE_GATE_POLICIES) == {"aggressive", "moderate", "conservative"}
    assert set(go.PROFILE_PORTFOLIO_BETA_CAPS) == {"aggressive", "moderate", "conservative"}


def test_portfolio_beta_cap_ladder_is_monotone() -> None:
    # the aggregate portfolio-beta cap ladder is a NEW concept, independent of the
    # per-instrument beta_graduated_caps throttle. Aggressive admits more beta.
    caps = go.PROFILE_PORTFOLIO_BETA_CAPS
    assert caps["aggressive"] > caps["moderate"] > caps["conservative"]


def test_risk_on_is_identity() -> None:
    eff = go.apply_gate_overlay(
        "moderate", "risk_on", base_risk_assets_cap=0.34, base_portfolio_beta_cap=0.80
    )
    assert eff.cvar_mult == 1.0
    assert eff.beta_mult == 1.0
    assert eff.risk_assets_cap == 0.34
    assert eff.beta_cap == 0.80  # identity: aggregate cap unchanged in risk_on
    assert eff.bl_view_confidence_multiplier == 1.0


def test_none_state_is_identity() -> None:
    eff = go.apply_gate_overlay(
        "aggressive", None, base_risk_assets_cap=0.45, base_portfolio_beta_cap=0.95
    )
    assert eff == go.apply_gate_overlay(
        "aggressive", "risk_on", base_risk_assets_cap=0.45, base_portfolio_beta_cap=0.95
    )


def test_risk_off_applies_formulas() -> None:
    shape = go.GATE_OVERLAY_SHAPE
    pol = go.PROFILE_GATE_POLICIES["moderate"]
    eff = go.apply_gate_overlay(
        "moderate", "risk_off", base_risk_assets_cap=0.34, base_portfolio_beta_cap=0.80
    )
    assert eff.cvar_mult == pytest.approx(1 - pol.intensity * shape.cvar_tightening)
    assert eff.beta_mult == pytest.approx(1 - pol.intensity * shape.beta_tightening)
    assert eff.risk_assets_cap == pytest.approx(
        0.34 - pol.intensity * shape.risk_assets_reduction
    )
    # aggregate beta cap = base · effective_beta_multiplier (NOT a per-asset change)
    assert eff.beta_cap == pytest.approx(0.80 * (1 - pol.intensity * shape.beta_tightening))
    assert eff.beta_cap < 0.80
    assert eff.bl_view_confidence_multiplier == 0.0  # v1 fixed risk_off policy


def test_risk_off_never_increases_risk() -> None:
    for profile in ("aggressive", "moderate", "conservative"):
        eff = go.apply_gate_overlay(
            profile, "risk_off", base_risk_assets_cap=0.40, base_portfolio_beta_cap=0.90
        )
        assert 0.0 < eff.cvar_mult <= 1.0
        assert 0.0 < eff.beta_mult <= 1.0
        assert eff.risk_assets_cap <= 0.40
        assert eff.beta_cap <= 0.90  # aggregate cap only ever tightens


def test_ladder_preserved_across_profiles() -> None:
    caps = {
        p: go.apply_gate_overlay(
            p, "risk_off", base_risk_assets_cap=0.40, base_portfolio_beta_cap=0.80
        ).cvar_mult
        for p in ("aggressive", "moderate", "conservative")
    }
    # the 3 profiles must not collapse to the same effective tightening
    assert len(set(round(v, 6) for v in caps.values())) == 3


def test_unknown_profile_raises() -> None:
    with pytest.raises(go.GateError, match="unknown profile"):
        go.apply_gate_overlay(
            "balanced", "risk_off", base_risk_assets_cap=0.30, base_portfolio_beta_cap=0.70
        )


def test_effective_risk_assets_cap_never_negative() -> None:
    eff = go.apply_gate_overlay(
        "conservative", "risk_off", base_risk_assets_cap=0.05, base_portfolio_beta_cap=0.40
    )
    assert eff.risk_assets_cap >= 0.0
