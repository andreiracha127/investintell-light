"""COMBO regime_aware policy core (spec §12-§20, model_version combo_policy_us_v1).

The strategic axis: one QuadrantPolicy per (profile, quadrant) holding FINAL
centers/half-widths (no HW_SCALE at runtime), the risk_assets_cap (equity+thematic
ceiling), the defensive_floor, and the versioned (empty-in-v1) FI sub-budgets. The
gate is a SEPARATE overlay (gate_overlay.py); it never touches these centers.

Seeds are research starting points to be calibrated in A4 (parameter freeze), not
final parameters. RECOVERY/EXPANSION centers are the legacy per-profile RISK_ON/
INFLATION rows RE-NORMALIZED to sum 1 (the old normalized_profile_centers did this
at runtime, which §15 forbids — so it is materialized here). SLOWDOWN/CONTRACTION
are the §17/§18 seeds verbatim (they already sum to 100%). No runtime normalization.
"""
from __future__ import annotations

from dataclasses import dataclass

# Frontier types (spec §3): the worker materializes lowercase strings, so these are
# str aliases — not enums. Track A produces the typed QuadrantSnapshot/GateSnapshot.
# `type` keyword (PEP 695) per the repo's ruff UP040 rule; still plain str aliases.
type Quadrant = str   # "recovery" | "expansion" | "slowdown" | "contraction"
type GateState = str  # "risk_on" | "risk_off"

POLICY_VERSION = "combo_policy_us_v1.0"

STRUCTURAL_SLEEVES: tuple[str, ...] = (
    "cash", "equity", "fixed_income", "thematic",
    "alternatives", "gold", "long_short",
)

# Versioned FI sub-bucket contract (spec §20). EMPTY in v1 (no FI tilts declared
# until calibrated); the compiler/post-verification (Plan C) consume the names.
FIXED_INCOME_BUCKETS: tuple[str, ...] = (
    "sovereign_short_intermediate",
    "sovereign_long_duration",
    "inflation_linked",
    "investment_grade_credit",
    "high_yield_preferred",
    "structured_private_credit",
)

QUADRANTS: tuple[str, ...] = ("recovery", "expansion", "slowdown", "contraction")
PROFILES: tuple[str, ...] = ("aggressive", "moderate", "conservative")


@dataclass(frozen=True)
class Budget:
    lo: float
    hi: float


@dataclass(frozen=True)
class QuadrantPolicy:
    center: dict[str, float]              # final centers, sum 1 over STRUCTURAL_SLEEVES
    half_width: dict[str, float]          # FINAL symmetric half-widths (no HW_SCALE)
    risk_assets_cap: float                # equity + thematic ceiling
    defensive_floor: float                # cash+fixed_income+gold+long_short floor
    fixed_income_sub_budgets: dict[str, Budget]  # empty {} in v1
    policy_version: str


def policy_bands(policy: QuadrantPolicy) -> dict[str, tuple[float, float]]:
    """Per-sleeve (lo, hi) from center ± half_width, clamped to [0, 1].

    No IPS re-widening and no HW_SCALE — the half-widths are already final
    (spec §19). The invariant validator (Task 2) guarantees 0≤lo≤center≤hi≤1.
    """
    bands: dict[str, tuple[float, float]] = {}
    for g in STRUCTURAL_SLEEVES:
        c = policy.center[g]
        hw = policy.half_width[g]
        bands[g] = (max(0.0, c - hw), min(1.0, c + hw))
    return bands


# Final symmetric half-widths per sleeve (spec §19 seed, collapsed to the SMALLER
# side so lo/hi never escape [0,1] given these centers). Same across quadrants in
# v1 (per-quadrant variation is a calibration degree of freedom, spec §33). These
# are RESEARCH widths — they are NOT guaranteed to fit every center (e.g. the §18
# seed sets conservative/contraction thematic center = 0%, but this width is 1pp).
_HALF_WIDTHS: dict[str, float] = {
    "cash": 0.04, "equity": 0.04, "fixed_income": 0.06, "thematic": 0.01,
    "alternatives": 0.03, "gold": 0.03, "long_short": 0.03,
}


def _materialize_half_widths(center: dict[str, float]) -> dict[str, float]:
    """Clamp each §19 seed half-width to the achievable band for this policy's center.

    `hw_eff[g] = min(seed_half_width[g], center[g], 1 − center[g])` so that the raw
    relationship `0 ≤ center[g] − hw_eff[g]` and `center[g] + hw_eff[g] ≤ 1` hold for
    EVERY sleeve — i.e. spec §15 (`0 ≤ lo_g ≤ center_g ≤ hi_g ≤ 1`) is satisfied on
    the MATERIALIZED policy, not merely after clamping inside ``policy_bands``.

    This is a deterministic STRUCTURAL-consistency rule applied once when building
    ``QUADRANT_POLICIES`` — NOT a runtime multiplier (no HW_SCALE is reintroduced).
    The §17/§18 center seeds and the §19 seed widths remain the source values; only
    the materialized per-policy half-width changes, and only where a seed width
    exceeds ``center`` or ``1 − center`` (today that is exactly one sleeve:
    conservative/contraction thematic, center = 0 → hw = 0, band [0, 0], meaning the
    policy allocates 0% thematic). A4 (parameter freeze) may recalibrate the seeds.
    """
    return {
        g: min(_HALF_WIDTHS[g], center[g], 1.0 - center[g])
        for g in STRUCTURAL_SLEEVES
    }


def _policy(
    center: dict[str, float], *, risk_assets_cap: float, defensive_floor: float
) -> QuadrantPolicy:
    return QuadrantPolicy(
        center=dict(center),
        half_width=_materialize_half_widths(center),
        risk_assets_cap=risk_assets_cap,
        defensive_floor=defensive_floor,
        fixed_income_sub_budgets={},
        policy_version=POLICY_VERSION,
    )


# RECOVERY/EXPANSION centers = legacy RISK_ON/INFLATION rows re-normalized to sum 1
# (raw_g / Σraw, residual absorbed in fixed_income so each row sums to 1.0 exactly).
# SLOWDOWN/CONTRACTION = §17/§18 seeds verbatim (already sum to 100%).
QUADRANT_POLICIES: dict[str, dict[str, QuadrantPolicy]] = {
    "aggressive": {
        "recovery": _policy(
            {"cash": 0.05, "equity": 0.33, "fixed_income": 0.31, "thematic": 0.08,
             "alternatives": 0.05, "gold": 0.10, "long_short": 0.08},
            risk_assets_cap=0.45, defensive_floor=0.28),
        "expansion": _policy(
            {"cash": 0.0825, "equity": 0.2680, "fixed_income": 0.2268,
             "thematic": 0.0722, "alternatives": 0.1237, "gold": 0.1340,
             "long_short": 0.0928},
            risk_assets_cap=0.42, defensive_floor=0.33),
        "slowdown": _policy(
            {"cash": 0.10, "equity": 0.26, "fixed_income": 0.21, "thematic": 0.04,
             "alternatives": 0.14, "gold": 0.14, "long_short": 0.11},
            risk_assets_cap=0.35, defensive_floor=0.45),
        "contraction": _policy(
            {"cash": 0.16, "equity": 0.18, "fixed_income": 0.35, "thematic": 0.02,
             "alternatives": 0.06, "gold": 0.11, "long_short": 0.12},
            risk_assets_cap=0.25, defensive_floor=0.54),
    },
    "moderate": {
        "recovery": _policy(
            {"cash": 0.10, "equity": 0.23, "fixed_income": 0.38, "thematic": 0.06,
             "alternatives": 0.05, "gold": 0.10, "long_short": 0.08},
            risk_assets_cap=0.34, defensive_floor=0.43),
        "expansion": _policy(
            {"cash": 0.1340, "equity": 0.1649, "fixed_income": 0.2991,
             "thematic": 0.0515, "alternatives": 0.1237, "gold": 0.1340,
             "long_short": 0.0928},
            risk_assets_cap=0.30, defensive_floor=0.48),
        "slowdown": _policy(
            {"cash": 0.15, "equity": 0.17, "fixed_income": 0.27, "thematic": 0.03,
             "alternatives": 0.13, "gold": 0.14, "long_short": 0.11},
            risk_assets_cap=0.25, defensive_floor=0.52),
        "contraction": _policy(
            {"cash": 0.22, "equity": 0.10, "fixed_income": 0.41, "thematic": 0.01,
             "alternatives": 0.05, "gold": 0.11, "long_short": 0.10},
            risk_assets_cap=0.15, defensive_floor=0.62),
    },
    "conservative": {
        "recovery": _policy(
            {"cash": 0.1402, "equity": 0.0467, "fixed_income": 0.4206,
             "thematic": 0.0280, "alternatives": 0.0467, "gold": 0.1682,
             "long_short": 0.1496},
            risk_assets_cap=0.20, defensive_floor=0.62),
        "expansion": _policy(
            {"cash": 0.1622, "equity": 0.0450, "fixed_income": 0.3243,
             "thematic": 0.0180, "alternatives": 0.1081, "gold": 0.1892,
             "long_short": 0.1532},
            risk_assets_cap=0.18, defensive_floor=0.67),
        "slowdown": _policy(
            {"cash": 0.21, "equity": 0.05, "fixed_income": 0.34, "thematic": 0.01,
             "alternatives": 0.10, "gold": 0.16, "long_short": 0.13},
            risk_assets_cap=0.12, defensive_floor=0.68),
        "contraction": _policy(
            {"cash": 0.28, "equity": 0.03, "fixed_income": 0.45, "thematic": 0.00,
             "alternatives": 0.04, "gold": 0.10, "long_short": 0.10},
            risk_assets_cap=0.08, defensive_floor=0.74),
    },
}


# --- Invariant validator (spec §15/§37). Fail-loud at startup (Task 10). ---------
_CENTER_TOL = 1e-6
_BAND_TOL = 1e-9


class PolicyError(ValueError):
    """A QuadrantPolicy invariant is violated (spec §15). Fail-loud at startup.

    Raised by ``validate_quadrant_policies`` on the FIRST violated invariant. The
    service must refuse to start if this is raised. The validator only CHECKS — it
    never normalizes or mutates the policies (spec §15 forbids runtime
    normalization), so the message names the offending profile/quadrant/sleeve and
    the violated invariant for an operator to fix the seed.
    """


def _validate_one(profile: str, quadrant: str, pol: QuadrantPolicy) -> None:
    """Check the §15 invariants for ONE materialized policy. Raises PolicyError.

    Bands are computed from the RAW ``center ± half_width`` (NOT ``policy_bands``,
    which clamps to [0,1]): the §15 invariant ``0 ≤ center − half_width`` must hold
    on the raw relationship, so a half_width that pushes ``lo`` negative is a
    violation even though ``policy_bands`` would clamp it back to 0.
    """
    where = f"{profile}/{quadrant}"
    if set(pol.center) != set(STRUCTURAL_SLEEVES):
        raise PolicyError(
            f"{where}: center sleeves must be exactly STRUCTURAL_SLEEVES, "
            f"got {sorted(pol.center)}"
        )
    if set(pol.half_width) != set(STRUCTURAL_SLEEVES):
        raise PolicyError(
            f"{where}: half_width sleeves must be exactly STRUCTURAL_SLEEVES, "
            f"got {sorted(pol.half_width)}"
        )
    total = sum(pol.center.values())
    if abs(total - 1.0) > _CENTER_TOL:
        raise PolicyError(f"{where}: centers must sum to 1, got {total}")
    sum_lo = 0.0
    sum_hi = 0.0
    for g in STRUCTURAL_SLEEVES:
        c = pol.center[g]
        hw = pol.half_width[g]
        lo = c - hw
        hi = c + hw
        if not (0.0 <= c <= 1.0):
            raise PolicyError(f"{where}: center[{g}]={c} outside [0,1]")
        if not (-_BAND_TOL <= lo <= c + _BAND_TOL <= hi + _BAND_TOL <= 1.0 + _BAND_TOL):
            raise PolicyError(
                f"{where}: band[{g}] violates 0<=lo<=center<=hi<=1 "
                f"(center={c}, half_width={hw}, lo={lo}, hi={hi})"
            )
        sum_lo += lo
        sum_hi += hi
    if sum_lo > 1.0 + _BAND_TOL:
        raise PolicyError(f"{where}: Σlo={sum_lo} must be <= 1")
    if sum_hi < 1.0 - _BAND_TOL:
        raise PolicyError(f"{where}: Σhi={sum_hi} must be >= 1")
    risk_assets = pol.center["equity"] + pol.center["thematic"]
    if risk_assets > pol.risk_assets_cap + _BAND_TOL:
        raise PolicyError(
            f"{where}: equity+thematic={risk_assets} exceeds "
            f"risk_assets_cap={pol.risk_assets_cap}"
        )
    defensive = (
        pol.center["cash"] + pol.center["fixed_income"]
        + pol.center["gold"] + pol.center["long_short"]
    )
    if defensive < pol.defensive_floor - _BAND_TOL:
        raise PolicyError(
            f"{where}: cash+fixed_income+gold+long_short={defensive} below "
            f"defensive_floor={pol.defensive_floor}"
        )
    if pol.policy_version != POLICY_VERSION:
        raise PolicyError(
            f"{where}: policy_version {pol.policy_version!r} != {POLICY_VERSION!r}"
        )


def validate_quadrant_policies(
    policies: dict[str, dict[str, QuadrantPolicy]] = QUADRANT_POLICIES,
) -> None:
    """Validate all 12 profile×quadrant policies (spec §15/§37).

    Raises :class:`PolicyError` on a violated invariant; returns ``None`` when every
    policy is valid AND all 12 profile×quadrant combinations are present. Intended to
    be called at service startup (Task 10): the service must not start if this raises.
    The validator only CHECKS — it never normalizes or mutates the policies (spec §15:
    no runtime normalization).

    Each policy that IS present is validated first, then completeness is checked. This
    ordering lets a caller pass a single deliberately-broken policy and get the
    specific invariant error (not a generic "missing the other 11") — while a complete
    set still fails loud if any of the 12 combinations is absent.
    """
    for profile in PROFILES:
        for quadrant in QUADRANTS:
            pol = policies.get(profile, {}).get(quadrant)
            if pol is not None:
                _validate_one(profile, quadrant, pol)
    for profile in PROFILES:
        if profile not in policies:
            raise PolicyError(f"missing policies for profile {profile!r}")
        for quadrant in QUADRANTS:
            if quadrant not in policies[profile]:
                raise PolicyError(f"missing policy for {profile}/{quadrant}")
