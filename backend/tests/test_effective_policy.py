import datetime as dt

import pytest

from app.optimizer import gate_overlay as go
from app.services import effective_policy as ep
from app.services import quadrant_policy as qp


def _snap(state: str = "risk_on", quadrant: str | None = "recovery"):
    from app.services.taa_bands import GateRegimeSnapshot

    return GateRegimeSnapshot(
        as_of=dt.date(2026, 1, 5), state=state, vote_count=0,
        trend_vote=False, credit_vote=False, drawdown_vote=False, dwell_days=1,
        last_flip=None, growth_score=0.01, inflation_score=0.02, quadrant=quadrant,
    )


def test_build_produces_cohesive_policy_risk_on() -> None:
    snap = _snap("risk_on", "recovery")
    eff = ep.build_effective_policy(snap, snap, "moderate", base_cvar_limit=0.05)
    assert isinstance(eff, ep.EffectiveRegimePolicy)
    assert eff.profile == "moderate"
    assert eff.quadrant == "recovery"
    assert eff.gate_state == "risk_on"
    assert eff.policy_version == qp.POLICY_VERSION
    # risk_on: cvar/beta/risk_assets identity, views full
    pol = qp.QUADRANT_POLICIES["moderate"]["recovery"]
    assert eff.cvar_limit == pytest.approx(0.05)
    assert eff.beta_cap == pytest.approx(go.PROFILE_PORTFOLIO_BETA_CAPS["moderate"])
    assert eff.risk_assets_cap == pytest.approx(pol.risk_assets_cap)
    assert eff.defensive_floor == pytest.approx(pol.defensive_floor)
    assert eff.bl_view_confidence_multiplier == 1.0
    assert eff.fixed_income_sub_budgets == {}
    assert eff.sleeve_budgets["equity"].lo == pytest.approx(
        qp.policy_bands(pol)["equity"][0]
    )
    assert eff.quadrant_snapshot_id and eff.gate_snapshot_id


def test_build_applies_gate_overlay_in_risk_off() -> None:
    snap = _snap("risk_off", "contraction")
    eff = ep.build_effective_policy(snap, snap, "aggressive", base_cvar_limit=0.06)
    base_beta = go.PROFILE_PORTFOLIO_BETA_CAPS["aggressive"]
    eg = go.apply_gate_overlay(
        "aggressive", "risk_off",
        base_risk_assets_cap=qp.QUADRANT_POLICIES["aggressive"]["contraction"].risk_assets_cap,
        base_portfolio_beta_cap=base_beta,
    )
    assert eff.cvar_limit == pytest.approx(0.06 * eg.cvar_mult)
    assert eff.cvar_limit < 0.06
    assert eff.beta_cap == pytest.approx(eg.beta_cap)
    assert eff.beta_cap < base_beta            # aggregate beta cap tightened
    assert eff.risk_assets_cap == pytest.approx(eg.risk_assets_cap)
    assert eff.bl_view_confidence_multiplier == 0.0  # views omitted in risk_off v1


def test_build_raises_on_unconsumable_quadrant() -> None:
    with pytest.raises(ep.EffectivePolicyError):
        ep.build_effective_policy(_snap("risk_on", None), _snap("risk_on", None),
                                  "moderate", base_cvar_limit=0.05)


def test_build_raises_on_missing_gate() -> None:
    with pytest.raises(ep.EffectivePolicyError):
        ep.build_effective_policy(_snap(), None, "moderate", base_cvar_limit=0.05)


def test_sleeve_budgets_cover_all_structural_sleeves() -> None:
    eff = ep.build_effective_policy(_snap(), _snap(), "conservative", base_cvar_limit=0.04)
    assert set(eff.sleeve_budgets) == set(qp.STRUCTURAL_SLEEVES)
    for b in eff.sleeve_budgets.values():
        assert isinstance(b, qp.Budget)
        assert 0.0 <= b.lo <= b.hi <= 1.0


def test_build_raises_on_unknown_profile() -> None:
    with pytest.raises(ep.EffectivePolicyError) as exc:
        ep.build_effective_policy(_snap(), _snap(), "nope", base_cvar_limit=0.05)
    assert "UNKNOWN_PROFILE" in str(exc.value)


def test_error_codes_are_structured() -> None:
    # non-consumable quadrant carries QUADRANT_UNAVAILABLE
    with pytest.raises(ep.EffectivePolicyError) as q:
        ep.build_effective_policy(_snap("risk_on", None), _snap(), "moderate",
                                  base_cvar_limit=0.05)
    assert "QUADRANT_UNAVAILABLE" in str(q.value)
    # missing gate carries GATE_UNAVAILABLE
    with pytest.raises(ep.EffectivePolicyError) as g:
        ep.build_effective_policy(_snap(), None, "moderate", base_cvar_limit=0.05)
    assert "GATE_UNAVAILABLE" in str(g.value)


def test_build_raises_policy_not_found_for_unknown_quadrant() -> None:
    # a quadrant string the profile has no policy for → POLICY_NOT_FOUND. We force it
    # by stubbing QUADRANTS to admit a label that has no QUADRANT_POLICIES entry.
    import app.services.effective_policy as ep_mod

    original = qp.QUADRANTS
    try:
        ep_mod.qp.QUADRANTS = (*original, "phantom")  # type: ignore[misc]
        with pytest.raises(ep.EffectivePolicyError) as exc:
            ep.build_effective_policy(_snap("risk_on", "phantom"),
                                      _snap("risk_on", "phantom"),
                                      "moderate", base_cvar_limit=0.05)
        assert "POLICY_NOT_FOUND" in str(exc.value)
    finally:
        ep_mod.qp.QUADRANTS = original  # type: ignore[misc]


def test_risk_off_tightens_relative_to_risk_on() -> None:
    on = ep.build_effective_policy(_snap("risk_on", "contraction"),
                                   _snap("risk_on", "contraction"),
                                   "aggressive", base_cvar_limit=0.06)
    off = ep.build_effective_policy(_snap("risk_off", "contraction"),
                                    _snap("risk_off", "contraction"),
                                    "aggressive", base_cvar_limit=0.06)
    assert off.cvar_limit < on.cvar_limit
    assert off.beta_cap < on.beta_cap
    assert off.risk_assets_cap < on.risk_assets_cap
    assert off.bl_view_confidence_multiplier < on.bl_view_confidence_multiplier
    # quadrant-driven numbers (defensive_floor, sleeve centers) are unchanged by gate
    assert off.defensive_floor == pytest.approx(on.defensive_floor)
    assert off.sleeve_budgets == on.sleeve_budgets


@pytest.mark.parametrize("bad_state", ["stale", "unknown", "risk-off", "RISK_OFF", " risk_off "])
def test_build_raises_on_malformed_gate_state(bad_state: str) -> None:
    # Adversarial: any gate state other than the exact literals risk_on/risk_off is
    # malformed (drift). It must fail loud as GATE_UNAVAILABLE, NOT silently fall
    # through to the risk_on identity overlay (a silent safety downgrade). Hyphenated
    # / cased / whitespace-padded values are NOT coerced into validity.
    with pytest.raises(ep.EffectivePolicyError) as exc:
        ep.build_effective_policy(
            _snap("risk_on", "recovery"), _snap(bad_state, "recovery"),
            "moderate", base_cvar_limit=0.05,
        )
    assert "GATE_UNAVAILABLE" in str(exc.value)


def test_profile_ladder_preserved_in_risk_off() -> None:
    # the per-profile intensity ladder → more aggressive admits a higher beta cap
    def beta_off(profile: str) -> float:
        return ep.build_effective_policy(
            _snap("risk_off", "slowdown"), _snap("risk_off", "slowdown"),
            profile, base_cvar_limit=0.05,
        ).beta_cap

    assert beta_off("aggressive") > beta_off("moderate") > beta_off("conservative")
