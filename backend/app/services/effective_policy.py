"""The central product of the COMBO policy core (decision B / spec §12).

``build_effective_policy`` composes a valid QuadrantSnapshot + a valid GateSnapshot +
a profile into ONE cohesive, frozen ``EffectiveRegimePolicy`` carrying the FINAL policy
numbers: per-sleeve budgets (center ± half_width), the gate-tightened cvar_limit /
beta_cap / risk_assets_cap, the quadrant defensive_floor, the BL view-confidence
multiplier, and lineage ids. The policy core validates and selects; it does NOT know
instruments, does NOT resolve feasibility, and does NOT call CVXPY (frontier A). The
beta_cap here is the AGGREGATE portfolio-beta cap — Plan C compiles it into a
LinearConstraint; this module only exposes the number (release-gate aware).
"""
from __future__ import annotations

from dataclasses import dataclass

from app.optimizer import gate_overlay
from app.services import quadrant_policy as qp
from app.services.taa_bands import GateRegimeSnapshot

# The worker materializes EXACTLY these two literals on the regime_gate_daily row.
# Anything else (absent, drifted "stale"/"unknown", or a hyphenated/cased/padded
# "risk-off") is non-consumable and must fail loud — NOT be coerced into validity
# (coercion would re-hide the very drift the boundary exists to catch).
_CONSUMABLE_GATE_STATES: frozenset[str] = frozenset({"risk_on", "risk_off"})


class EffectivePolicyError(ValueError):
    """A snapshot is non-consumable or an input is missing (spec §31).

    Fail-loud; the builder re-raises this as a structured ``BuilderError`` → 422. The
    message is prefixed with a structured code (``QUADRANT_UNAVAILABLE`` /
    ``GATE_UNAVAILABLE`` / ``POLICY_NOT_FOUND`` / ``UNKNOWN_PROFILE``) so the caller
    can branch on the failure mode without parsing free text.
    """


@dataclass(frozen=True)
class EffectiveRegimePolicy:
    profile: str
    quadrant: qp.Quadrant
    gate_state: qp.GateState
    policy_version: str
    quadrant_snapshot_id: str
    gate_snapshot_id: str
    sleeve_budgets: dict[str, qp.Budget]
    fixed_income_sub_budgets: dict[str, qp.Budget]
    cvar_limit: float
    beta_cap: float            # AGGREGATE portfolio-beta cap (β_portfolio ≤ beta_cap)
    risk_assets_cap: float
    defensive_floor: float
    bl_view_confidence_multiplier: float


def _snapshot_id(snap: GateRegimeSnapshot, kind: str) -> str:
    # v1: quadrant + gate are materialized on one regime_gate_daily row, so both ids
    # derive from as_of. Track A will split them into independent snapshot ids.
    return f"{kind}:{snap.as_of.isoformat()}"


def build_effective_policy(
    quadrant_snapshot: GateRegimeSnapshot | None,
    gate_snapshot: GateRegimeSnapshot | None,
    profile: str,
    *,
    base_cvar_limit: float,
) -> EffectiveRegimePolicy:
    """Produce the cohesive ``EffectiveRegimePolicy`` (decision B).

    Fail-loud on a non-consumable quadrant/gate or a missing policy. The quadrant
    snapshot is consumable iff it carries a known ``quadrant``; the gate snapshot is
    consumable iff its ``state`` is one of the EXACT literals ``risk_on``/``risk_off``
    (a missing, drifted, or malformed value fails loud as ``GATE_UNAVAILABLE`` rather
    than silently downgrading safety). The gate overlay (``apply_gate_overlay``)
    tightens cvar/beta/risk-assets in ``risk_off`` and is the identity in ``risk_on``.
    """
    if profile not in qp.PROFILES:
        raise EffectivePolicyError(f"UNKNOWN_PROFILE: unknown profile {profile!r}")
    if quadrant_snapshot is None:
        raise EffectivePolicyError("QUADRANT_UNAVAILABLE: no quadrant snapshot")
    if gate_snapshot is None:
        raise EffectivePolicyError("GATE_UNAVAILABLE: no gate snapshot")
    quadrant = quadrant_snapshot.quadrant
    if quadrant is None or quadrant not in qp.QUADRANTS:
        raise EffectivePolicyError(
            f"QUADRANT_UNAVAILABLE: non-consumable quadrant {quadrant!r}"
        )
    gate_state = gate_snapshot.state
    if gate_state not in _CONSUMABLE_GATE_STATES:
        # Fail-loud on a missing OR malformed/drifted gate value (spec §2/§11/§23):
        # gate absent does NOT become risk_on, and the gate never silently increases
        # risk. Compared against the EXACT literals — no .lower()/.strip() coercion.
        raise EffectivePolicyError(
            f"GATE_UNAVAILABLE: non-consumable gate state {gate_state!r}"
        )
    by_quadrant = qp.QUADRANT_POLICIES.get(profile)
    if by_quadrant is None or quadrant not in by_quadrant:
        raise EffectivePolicyError(
            f"POLICY_NOT_FOUND: no policy for {profile}/{quadrant}"
        )
    policy = by_quadrant[quadrant]
    eff_gate = gate_overlay.apply_gate_overlay(
        profile,
        gate_state,
        base_risk_assets_cap=policy.risk_assets_cap,
        base_portfolio_beta_cap=gate_overlay.PROFILE_PORTFOLIO_BETA_CAPS[profile],
    )
    bands = qp.policy_bands(policy)
    sleeve_budgets = {
        sleeve: qp.Budget(lo=lo, hi=hi) for sleeve, (lo, hi) in bands.items()
    }
    return EffectiveRegimePolicy(
        profile=profile,
        quadrant=quadrant,
        gate_state=gate_state,
        policy_version=policy.policy_version,
        quadrant_snapshot_id=_snapshot_id(quadrant_snapshot, "quadrant"),
        gate_snapshot_id=_snapshot_id(gate_snapshot, "gate"),
        sleeve_budgets=sleeve_budgets,
        fixed_income_sub_budgets=dict(policy.fixed_income_sub_budgets),  # {} in v1
        cvar_limit=base_cvar_limit * eff_gate.cvar_mult,
        beta_cap=eff_gate.beta_cap,
        risk_assets_cap=eff_gate.risk_assets_cap,
        defensive_floor=policy.defensive_floor,
        bl_view_confidence_multiplier=eff_gate.bl_view_confidence_multiplier,
    )
