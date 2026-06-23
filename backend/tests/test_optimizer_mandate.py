# backend/tests/test_optimizer_mandate.py
"""T2F-2: mandate -> risk-aversion (delta) ladder, ported from the legacy
quant_engine.mandate_risk_aversion. Pure, no I/O, no logging. An explicit
delta override wins (clamped to [DELTA_MIN, DELTA_MAX]); a mandate label maps
through the ladder; unknown/absent -> DEFAULT_DELTA (== bl.DEFAULT_DELTA)."""

import math

import pytest

from app.optimizer import black_litterman as bl
from app.optimizer.mandate import (
    DELTA_MAX,
    DELTA_MIN,
    MANDATE_DELTA,
    resolve_delta,
)


def test_default_matches_bl_default_delta() -> None:
    # The fallback must be the same 2.5 the optimizer already uses.
    assert MANDATE_DELTA["moderate"] == bl.DEFAULT_DELTA


@pytest.mark.parametrize(
    ("mandate", "expected"),
    [
        ("conservative", 4.5),
        ("Conservative", 4.5),  # case-insensitive
        ("moderate", 2.5),
        ("balanced", 2.5),
        ("aggressive", 1.5),
        ("growth", 1.5),
        ("moderate-conservative", 3.5),  # dash normalised to underscore
        ("moderate aggressive", 2.0),    # whitespace normalised
    ],
)
def test_mandate_maps_to_ladder(mandate: str, expected: float) -> None:
    assert resolve_delta(None, mandate) == expected


def test_unknown_mandate_falls_back_to_default() -> None:
    assert resolve_delta(None, "wildly_unknown") == bl.DEFAULT_DELTA


def test_no_inputs_uses_default() -> None:
    assert resolve_delta(None, None) == bl.DEFAULT_DELTA


def test_explicit_delta_overrides_mandate() -> None:
    # Override beats the mandate ladder entirely.
    assert resolve_delta(3.0, "aggressive") == 3.0


def test_explicit_delta_is_clamped_into_range() -> None:
    assert resolve_delta(100.0, None) == DELTA_MAX
    assert resolve_delta(0.0001, None) == DELTA_MIN
    assert DELTA_MIN == 0.5
    assert DELTA_MAX == 10.0


def test_non_finite_override_discarded_then_mandate() -> None:
    # NaN/Inf override is dropped; mandate is used instead.
    assert resolve_delta(math.nan, "conservative") == 4.5
    assert resolve_delta(math.inf, None) == bl.DEFAULT_DELTA


def test_non_positive_override_discarded_then_default() -> None:
    assert resolve_delta(-1.0, None) == bl.DEFAULT_DELTA


# ── COMBO regime_aware: per-mandate GAMMA (utility risk-aversion), DECOUPLED ──
# from the equilibrium delta. The calibrated trio is the return/risk dial.
from app.optimizer.mandate import (  # noqa: E402
    DELTA_MARKET,
    GAMMA_MAX,
    GAMMA_MIN,
    MANDATE_GAMMA,
    resolve_gamma,
)


def test_gamma_ladder_maps_calibrated_trio() -> None:
    assert resolve_gamma(None, "aggressive") == 1.90
    assert resolve_gamma(None, "moderate") == 4.75
    assert resolve_gamma(None, "conservative") == 13.50


def test_gamma_decoupled_from_equilibrium_delta() -> None:
    # The whole point of the port: the per-mandate UTILITY gamma is NOT the
    # equilibrium delta. Conservative: gamma 13.5 (utility curvature) vs the
    # market delta 2.5 that generates pi for every profile.
    assert resolve_gamma(None, "conservative") != resolve_delta(None, "conservative")
    assert DELTA_MARKET == 2.5


def test_gamma_override_clamped() -> None:
    assert resolve_gamma(100.0, None) == GAMMA_MAX
    assert resolve_gamma(0.0001, None) == GAMMA_MIN


def test_gamma_unknown_or_absent_uses_moderate() -> None:
    assert resolve_gamma(None, None) == MANDATE_GAMMA["moderate"]
    assert resolve_gamma(None, "wildly_unknown") == MANDATE_GAMMA["moderate"]


def test_gamma_aliases_and_normalisation() -> None:
    assert resolve_gamma(None, "growth") == 1.90
    assert resolve_gamma(None, "Defensive") == 13.50
    assert resolve_gamma(None, "moderate-aggressive") == 3.0  # interpolated rung
