"""COMBO startup validation (spec §37). Run in the app lifespan BEFORE serving.

Validates: the 12 QuadrantPolicies (centers sum 1, bands in [0,1], risk_assets_cap,
defensive_floor); the gate shape + per-profile ladder (3 profiles do not collapse
to identical effective tightening, and the aggregate portfolio-beta cap ladder is
strictly monotone); and that NO legacy symbol survives on the production module
(combined_regime, band_state_from_quadrant, effective_class_bands, goldfix_target,
HW_SCALE, PROFILE_CENTERS, DEFAULT_TAA_BANDS, normalized_profile_centers,
profile_sleeve_bands). Any failure aborts the boot (fail-loud, not log-and-continue).
"""
from __future__ import annotations

from app.optimizer import gate_overlay
from app.services import quadrant_policy, taa_bands

_LEGACY_SYMBOLS = (
    "combined_regime",
    "band_state_from_quadrant",
    "effective_class_bands",
    "goldfix_target",
    "HW_SCALE",
    "PROFILE_CENTERS",
    "DEFAULT_TAA_BANDS",
    "normalized_profile_centers",
    "profile_sleeve_bands",
)


class StartupValidationError(RuntimeError):
    """A COMBO startup invariant failed; the service must not start."""


def _validate_gate_ladder() -> None:
    # cvar_mult must differ across the 3 profiles in risk_off (ladder, spec §23).
    # Read the module globals at call time (not import time) so a monkeypatched
    # PROFILE_GATE_POLICIES / PROFILE_PORTFOLIO_BETA_CAPS is honoured.
    muls = {
        p: gate_overlay.apply_gate_overlay(
            p,
            "risk_off",
            base_risk_assets_cap=0.40,
            base_portfolio_beta_cap=gate_overlay.PROFILE_PORTFOLIO_BETA_CAPS[p],
        ).cvar_mult
        for p in quadrant_policy.PROFILES
    }
    if len({round(v, 9) for v in muls.values()}) < len(muls):
        raise StartupValidationError(
            f"gate ladder collapsed — profiles share cvar_mult: {muls}"
        )
    # the aggregate portfolio-beta cap ladder must also be strictly monotone (spec §23).
    caps = gate_overlay.PROFILE_PORTFOLIO_BETA_CAPS
    if not (caps["aggressive"] > caps["moderate"] > caps["conservative"]):
        raise StartupValidationError(
            f"portfolio-beta cap ladder not monotone: {caps}"
        )


def _validate_no_legacy() -> None:
    for name in _LEGACY_SYMBOLS:
        if hasattr(taa_bands, name):
            raise StartupValidationError(
                f"legacy symbol {name!r} still present on taa_bands (spec §I)"
            )


def validate_combo_startup() -> None:
    """Run every COMBO startup check; raise StartupValidationError on the first
    failure. Wraps quadrant_policy.PolicyError / gate_overlay.GateError so the
    boot path sees a single error type.

    ``QUADRANT_POLICIES`` is passed explicitly (not via the validator's default
    argument, which binds at definition time) so a monkeypatched policy set is
    honoured — the boot guard reflects the live module state, not a frozen snapshot.
    """
    try:
        quadrant_policy.validate_quadrant_policies(quadrant_policy.QUADRANT_POLICIES)
    except quadrant_policy.PolicyError as exc:
        raise StartupValidationError(f"policy invariant failed: {exc}") from exc
    try:
        _validate_gate_ladder()
    except gate_overlay.GateError as exc:
        raise StartupValidationError(f"gate shape invalid: {exc}") from exc
    _validate_no_legacy()
