"""Gate overlay for COMBO regime_aware (spec §21-§24).

The gate is orthogonal to the quadrant (spec §12): it does not change centers,
taxonomy, or the market prior — it only TIGHTENS the risk envelope in risk_off.
A common shape (GateOverlayShape) is scaled by a per-profile intensity into the
effective multipliers (spec §22). risk_on is the identity. In v1 the risk_off
BL view-confidence multiplier is FIXED at 0.0 (μ = π; views omitted) — a policy,
not a hyperparameter (spec §24).
"""
from __future__ import annotations

from dataclasses import dataclass

from app.services.quadrant_policy import PROFILES, GateState


class GateError(ValueError):
    """Invalid gate input (unknown profile) or invariant violation. Fail-loud."""


@dataclass(frozen=True)
class GateOverlayShape:
    cvar_tightening: float        # fraction the CVaR cap is cut at intensity 1
    beta_tightening: float        # fraction the AGGREGATE portfolio-beta cap is cut at intensity 1
    risk_assets_reduction: float  # absolute pp the equity+thematic cap drops at intensity 1


@dataclass(frozen=True)
class ProfileGatePolicy:
    intensity: float                      # ∈ [0,1]; preserves the per-profile ladder
    bl_view_confidence_multiplier: float  # 0.0 in risk_off v1 (μ = π)


@dataclass(frozen=True)
class EffectiveGate:
    cvar_mult: float
    beta_mult: float
    risk_assets_cap: float
    beta_cap: float  # AGGREGATE portfolio-beta cap = base_portfolio_beta_cap · beta_mult
    bl_view_confidence_multiplier: float


# Common v1 shape (calibration_seed_v0.1; to be validated by A4 ablation). At
# intensity 1: CVaR cap ×0.65, aggregate portfolio-beta cap ×0.75,
# equity+thematic cap −0.07. This keeps risk_off hard enough to brake risk while
# preserving profile separation and avoiding the old aggressive/recovery 1pp
# geometric infeasibility.
GATE_OVERLAY_SHAPE = GateOverlayShape(
    cvar_tightening=0.35,
    beta_tightening=0.25,
    risk_assets_reduction=0.07,
)

# Per-profile intensity ladder (seed): the more aggressive the profile, the
# harder the risk-off brake. bl_view_confidence_multiplier fixed 0.0 (spec §24).
PROFILE_GATE_POLICIES: dict[str, ProfileGatePolicy] = {
    "aggressive": ProfileGatePolicy(intensity=1.00, bl_view_confidence_multiplier=0.0),
    "moderate": ProfileGatePolicy(intensity=0.70, bl_view_confidence_multiplier=0.0),
    "conservative": ProfileGatePolicy(intensity=0.50, bl_view_confidence_multiplier=0.0),
}

# Per-profile AGGREGATE portfolio-beta cap ladder (seed; calibrated in A4). This is
# the profile-level β_portfolio ≤ cap; it is a NEW, independent concept from the
# per-instrument throttle in taa_bands.beta_graduated_caps (which is preserved as-is).
# Monotone: aggressive admits more aggregate beta than conservative.
PROFILE_PORTFOLIO_BETA_CAPS: dict[str, float] = {
    "aggressive": 0.85,
    "moderate": 0.55,
    "conservative": 0.30,
}

_IDENTITY_BL_MULT = 1.0


def _validate_shape(shape: GateOverlayShape) -> None:
    if not 0.0 <= shape.cvar_tightening < 1.0:
        raise GateError(f"cvar_tightening must be in [0,1), got {shape.cvar_tightening}")
    if not 0.0 <= shape.beta_tightening < 1.0:
        raise GateError(f"beta_tightening must be in [0,1), got {shape.beta_tightening}")
    if shape.risk_assets_reduction < 0.0:
        raise GateError(
            f"risk_assets_reduction must be >= 0, got {shape.risk_assets_reduction}"
        )


def _validate_profile_policy(profile: str, pol: ProfileGatePolicy) -> None:
    if not 0.0 <= pol.intensity <= 1.0:
        raise GateError(f"{profile}: intensity must be in [0,1], got {pol.intensity}")
    if not 0.0 <= pol.bl_view_confidence_multiplier <= 1.0:
        raise GateError(
            f"{profile}: bl_view_confidence_multiplier must be in [0,1], "
            f"got {pol.bl_view_confidence_multiplier}"
        )


def apply_gate_overlay(
    profile: str,
    state: GateState | None,
    *,
    base_risk_assets_cap: float,
    base_portfolio_beta_cap: float,
) -> EffectiveGate:
    """Effective risk envelope after the gate (spec §22).

    risk_on / None → identity (no tightening); a non-empty UNRECOGNIZED state raises
    ``GateError`` (drift is fail-loud, never the identity). risk_off →
    cvar_mult = 1 − intensity·cvar_tightening; beta_mult = 1 − intensity·
    beta_tightening; risk_assets_cap = base − intensity·risk_assets_reduction
    (floored at 0); beta_cap = base_portfolio_beta_cap · beta_mult (the AGGREGATE
    portfolio-beta cap, NOT a per-asset change); bl_view_confidence_multiplier from
    the per-profile policy (0.0 in v1). Validates §23 invariants.
    """
    if profile not in PROFILES:
        raise GateError(f"unknown profile {profile!r}")
    # Defense in depth (the policy core already rejects a malformed state before we
    # get here): None is the documented safe default (→ identity), risk_off tightens,
    # risk_on is the identity. ANYTHING else is drift — a non-empty unrecognized
    # state must RAISE rather than silently fall through to the risk_on identity
    # (the unsafe path the adversarial review caught). No .lower()/.strip() coercion.
    if state is not None and state not in ("risk_on", "risk_off"):
        raise GateError(f"unknown gate state {state!r}")
    if state != "risk_off":
        return EffectiveGate(
            cvar_mult=1.0,
            beta_mult=1.0,
            risk_assets_cap=base_risk_assets_cap,
            beta_cap=base_portfolio_beta_cap,
            bl_view_confidence_multiplier=_IDENTITY_BL_MULT,
        )
    shape = GATE_OVERLAY_SHAPE
    pol = PROFILE_GATE_POLICIES[profile]
    _validate_shape(shape)
    _validate_profile_policy(profile, pol)
    cvar_mult = 1.0 - pol.intensity * shape.cvar_tightening
    beta_mult = 1.0 - pol.intensity * shape.beta_tightening
    risk_assets_cap = max(0.0, base_risk_assets_cap - pol.intensity * shape.risk_assets_reduction)
    beta_cap = base_portfolio_beta_cap * beta_mult
    if not 0.0 < cvar_mult <= 1.0:
        raise GateError(f"{profile}: cvar_mult {cvar_mult} not in (0,1]")
    if not 0.0 < beta_mult <= 1.0:
        raise GateError(f"{profile}: beta_mult {beta_mult} not in (0,1]")
    return EffectiveGate(
        cvar_mult=cvar_mult,
        beta_mult=beta_mult,
        risk_assets_cap=risk_assets_cap,
        beta_cap=beta_cap,
        bl_view_confidence_multiplier=pol.bl_view_confidence_multiplier,
    )


def bl_confidence_multiplier(effective_gate: EffectiveGate) -> float:
    """Single source for the BL view-confidence multiplier (spec §24).

    0.0 → μ = π (views OMITTED entirely); the consumer must NEVER pass
    confidence=0 to omega_idzorek. 0.5 → half confidence; 1.0 → normal (risk_on
    identity). The aggregate portfolio-beta cap is EffectiveGate.beta_cap,
    compiled into a LinearConstraint by Plan C — there is deliberately NO
    per-asset effective_beta_coef throttle here.
    """
    return effective_gate.bl_view_confidence_multiplier
