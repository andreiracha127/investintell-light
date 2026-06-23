"""Mandate -> risk-aversion (delta) ladder for the Black-Litterman layer.

Ported from the legacy quant_engine.mandate_risk_aversion (Grinold-Kahn /
CFA L3 arithmetic ladder). Pure: no I/O, no logging. This is the only place
an investor mandate label is turned into the delta the optimizer consumes; it
keeps Conservative / Moderate / Aggressive clients off the same equilibrium.

    Conservative  -> 4.5   (variance heavily penalised)
    Moderate      -> 2.5   (== bl.DEFAULT_DELTA, the fallback)
    Aggressive    -> 1.5   (return-tilted)

Resolution: an explicit ``delta`` override wins and is clamped to
[DELTA_MIN, DELTA_MAX]; a non-finite/non-positive override is discarded and we
fall through to the mandate, then to DEFAULT_DELTA. A mandate label is
normalised (whitespace/dashes -> underscore, lowercased) and looked up; an
unknown label falls back to DEFAULT_DELTA. The legacy 'aggressive' -> 'growth'
deprecation alias is dropped (both rungs already map to 1.5, so the numeric
result is identical and the Light optimizer is log-free by contract).
"""

from __future__ import annotations

import math
import re

from app.optimizer.black_litterman import DEFAULT_DELTA

# Arithmetic ladder (lowercase, underscore-separated keys).
MANDATE_DELTA: dict[str, float] = {
    "conservative": 4.5,
    "defensive": 4.5,
    "moderate_conservative": 3.5,
    "moderate": 2.5,
    "balanced": 2.5,
    "moderate_aggressive": 2.0,
    "aggressive": 1.5,
    "growth": 1.5,
}

DELTA_MIN = 0.5    # Grinold-Kahn lower bound for institutional lambda
DELTA_MAX = 10.0   # upper bound — beyond this optimizer scaling fails

_KEY_NORMALISER = re.compile(r"[\s\-]+")


def normalise_mandate(mandate: str) -> str:
    """Collapse runs of whitespace/dashes into one underscore; lowercase."""
    return _KEY_NORMALISER.sub("_", mandate.strip().lower())


def resolve_delta(delta: float | None, mandate: str | None) -> float:
    """Resolve the effective delta from an override, a mandate, or the default.

    Priority: finite positive ``delta`` (clamped to [DELTA_MIN, DELTA_MAX]) >
    ``mandate`` ladder lookup > DEFAULT_DELTA. Never returns NaN/Inf.
    """
    if delta is not None and math.isfinite(delta) and delta > 0:
        return float(max(DELTA_MIN, min(DELTA_MAX, delta)))
    if mandate:
        key = normalise_mandate(mandate)
        if key in MANDATE_DELTA:
            return MANDATE_DELTA[key]
    return float(DEFAULT_DELTA)


# ── regime_aware (COMBO) per-mandate GAMMA + single market delta ─────────────
# The BL max-utility motor uses TWO decoupled deltas (harness design,
# combo-bl-utility-calibration): a single market-wide DELTA_MARKET generates the
# equilibrium prior π = DELTA_MARKET·Σ·w_mkt (identical for every profile), while
# GAMMA is the PER-MANDATE utility curvature — the calibrated COMBO return/risk
# dial. Conflating them (e.g. setting MANDATE_DELTA to the GAMMA trio) would
# wrongly scale the conservative's equilibrium return by 13.5. Calibrated trio:
# aggressive 1.90 / moderate 4.75 / conservative 13.50 (beta ladder 0.80/0.50/0.21).
# The two intermediate rungs are GEOMETRIC interpolations of the adjacent
# calibrated rungs (√(4.75·13.50)≈8.0, √(1.90·4.75)≈3.0) — not separately tuned.
DELTA_MARKET = 2.5
MANDATE_GAMMA: dict[str, float] = {
    "conservative": 13.50,
    "defensive": 13.50,
    "moderate_conservative": 8.0,
    "moderate": 4.75,
    "balanced": 4.75,
    "moderate_aggressive": 3.0,
    "aggressive": 1.90,
    "growth": 1.90,
}
GAMMA_MIN = 0.5     # return-tilted lower bound
GAMMA_MAX = 30.0    # beyond this the utility solve degenerates toward min-variance


def resolve_gamma(gamma: float | None, mandate: str | None) -> float:
    """Resolve the per-mandate UTILITY risk-aversion (GAMMA) for the regime_aware
    BL max-utility objective — DECOUPLED from the equilibrium ``delta``.

    Priority mirrors :func:`resolve_delta`: a finite positive ``gamma`` override
    wins (clamped to [GAMMA_MIN, GAMMA_MAX]); a mandate label maps through
    ``MANDATE_GAMMA``; unknown/absent falls back to the moderate rung. Never
    returns NaN/Inf.
    """
    if gamma is not None and math.isfinite(gamma) and gamma > 0:
        return float(max(GAMMA_MIN, min(GAMMA_MAX, gamma)))
    if mandate:
        key = normalise_mandate(mandate)
        if key in MANDATE_GAMMA:
            return MANDATE_GAMMA[key]
    return MANDATE_GAMMA["moderate"]


# Per-mandate hard 95% daily-CVaR SAFETY cap for the regime_aware BL max-utility
# solve (calibrated harness CVAR_LIMIT). Note: per the calibration, CVaR is the
# SAFETY wall, not the active lever — gamma + the regime bands usually bind first.
# In daily-return units, matching the scenario rows. Tightened in risk_off states
# by the caller (apply_regime_cvar_limit). Intermediate rungs interpolate linearly.
MANDATE_CVAR_LIMIT: dict[str, float] = {
    "conservative": 0.016,
    "defensive": 0.016,
    "moderate_conservative": 0.019,
    "moderate": 0.022,
    "balanced": 0.022,
    "moderate_aggressive": 0.026,
    "aggressive": 0.030,
    "growth": 0.030,
}


def resolve_cvar_limit(cvar_limit: float | None, mandate: str | None) -> float:
    """Resolve the per-mandate daily-CVaR safety cap for regime_aware. A finite
    positive ``cvar_limit`` override wins; otherwise the mandate ladder; otherwise
    the moderate rung. Never returns NaN/Inf or a non-positive value."""
    if cvar_limit is not None and math.isfinite(cvar_limit) and cvar_limit > 0:
        return float(cvar_limit)
    if mandate:
        key = normalise_mandate(mandate)
        if key in MANDATE_CVAR_LIMIT:
            return MANDATE_CVAR_LIMIT[key]
    return MANDATE_CVAR_LIMIT["moderate"]
