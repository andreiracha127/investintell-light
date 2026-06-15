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
