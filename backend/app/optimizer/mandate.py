"""Profile-calibrated COMBO risk parameters and BL delta helpers.

``profile`` is the calibrated model axis: conservative / moderate / aggressive.
Portfolio mandates/IPS constraints are customer-specific construction limits and
do not change gamma, CVaR, beta caps, or equilibrium delta. A caller that wants a
different generic BL equilibrium delta must pass ``bl.delta`` explicitly.
"""

from __future__ import annotations

import re

from app.optimizer.black_litterman import DEFAULT_DELTA

DELTA_MIN = 0.5
DELTA_MAX = 10.0

_KEY_NORMALISER = re.compile(r"[\s\-]+")


def _normalise_key(value: str) -> str:
    """Collapse runs of whitespace/dashes into one underscore; lowercase."""
    return _KEY_NORMALISER.sub("_", value.strip().lower())


def resolve_delta(delta: float | None) -> float:
    """Resolve generic BL equilibrium delta from an explicit override or default.

    Customer mandate/IPS labels do not affect this value.
    """
    if delta is not None and delta > 0:
        return float(max(DELTA_MIN, min(DELTA_MAX, delta)))
    return float(DEFAULT_DELTA)


# ── regime_aware (COMBO) per-profile GAMMA + single market delta ─────────────
# The BL max-utility motor uses TWO decoupled deltas (harness design,
# combo-bl-utility-calibration): a single market-wide DELTA_MARKET generates the
# equilibrium prior π = DELTA_MARKET·Σ·w_mkt (identical for every profile), while
# GAMMA is the PER-PROFILE utility curvature — the calibrated COMBO return/risk
# dial. Conflating it with mandate/customer constraints would make the master
# profile unstable. Calibrated trio:
# aggressive 1.90 / moderate 4.75 / conservative 13.50 (beta ladder 0.80/0.50/0.21).
DELTA_MARKET = 2.5
PROFILE_GAMMA: dict[str, float] = {
    "conservative": 13.50,
    "moderate": 4.75,
    "aggressive": 1.90,
}
GAMMA_MIN = 0.5     # return-tilted lower bound
GAMMA_MAX = 30.0    # beyond this the utility solve degenerates toward min-variance


def resolve_profile_gamma(profile: str | None) -> float:
    """Resolve calibrated COMBO utility GAMMA from one canonical profile.

    ``profile`` is the master calibration axis. Customer mandate/IPS constraints
    do not change this number; they enter as explicit construction constraints.
    Unknown/absent falls back to the moderate master.
    """
    if profile:
        key = _normalise_key(profile)
        if key in PROFILE_GAMMA:
            return PROFILE_GAMMA[key]
    return PROFILE_GAMMA["moderate"]


# Per-profile hard 95% daily-CVaR SAFETY cap for the regime_aware BL max-utility
# solve. This is part of the calibrated master profile, not a customer-facing
# mandate knob. In daily-return units, matching the scenario rows. Tightened in
# risk_off states by the gate overlay.
PROFILE_CVAR_LIMIT: dict[str, float] = {
    "conservative": 0.016,
    "moderate": 0.022,
    "aggressive": 0.030,
}


def resolve_profile_cvar_limit(profile: str | None) -> float:
    """Resolve the calibrated daily-CVaR safety cap from the canonical profile."""
    if profile:
        key = _normalise_key(profile)
        if key in PROFILE_CVAR_LIMIT:
            return PROFILE_CVAR_LIMIT[key]
    return PROFILE_CVAR_LIMIT["moderate"]
