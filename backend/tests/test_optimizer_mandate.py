"""Profile-calibrated COMBO risk parameters and generic BL delta helpers."""

import pytest

from app.optimizer import black_litterman as bl
from app.optimizer.mandate import (
    DELTA_MARKET,
    DELTA_MAX,
    DELTA_MIN,
    GAMMA_MAX,
    GAMMA_MIN,
    PROFILE_CVAR_LIMIT,
    PROFILE_GAMMA,
    resolve_delta,
    resolve_profile_cvar_limit,
    resolve_profile_gamma,
)


def test_default_matches_bl_default_delta() -> None:
    assert resolve_delta(None) == bl.DEFAULT_DELTA


def test_explicit_delta_is_clamped_into_range() -> None:
    assert resolve_delta(100.0) == DELTA_MAX
    assert resolve_delta(0.0001) == DELTA_MIN
    assert DELTA_MIN == 0.5
    assert DELTA_MAX == 10.0


def test_non_positive_delta_uses_default() -> None:
    assert resolve_delta(-1.0) == bl.DEFAULT_DELTA
    assert resolve_delta(0.0) == bl.DEFAULT_DELTA


def test_profile_gamma_maps_calibrated_trio() -> None:
    assert resolve_profile_gamma("aggressive") == 1.90
    assert resolve_profile_gamma("moderate") == 4.75
    assert resolve_profile_gamma("conservative") == 13.50
    assert set(PROFILE_GAMMA) == {"aggressive", "moderate", "conservative"}


def test_profile_gamma_decoupled_from_equilibrium_delta() -> None:
    assert resolve_profile_gamma("conservative") != resolve_delta(None)
    assert DELTA_MARKET == 2.5


def test_profile_gamma_unknown_or_absent_uses_moderate() -> None:
    assert resolve_profile_gamma(None) == PROFILE_GAMMA["moderate"]
    assert resolve_profile_gamma("wildly_unknown") == PROFILE_GAMMA["moderate"]


def test_profile_gamma_rejects_legacy_intermediate_mandates() -> None:
    assert resolve_profile_gamma("moderate-aggressive") == PROFILE_GAMMA["moderate"]
    assert resolve_profile_gamma("defensive") == PROFILE_GAMMA["moderate"]


def test_gamma_bounds_remain_documented() -> None:
    assert GAMMA_MIN == 0.5
    assert GAMMA_MAX == 30.0


def test_profile_cvar_limit_maps_calibrated_trio() -> None:
    assert resolve_profile_cvar_limit("aggressive") == 0.030
    assert resolve_profile_cvar_limit("moderate") == 0.022
    assert resolve_profile_cvar_limit("conservative") == 0.016
    assert set(PROFILE_CVAR_LIMIT) == {"aggressive", "moderate", "conservative"}


def test_profile_cvar_limit_unknown_or_absent_uses_moderate() -> None:
    assert resolve_profile_cvar_limit(None) == PROFILE_CVAR_LIMIT["moderate"]
    assert resolve_profile_cvar_limit("wildly_unknown") == PROFILE_CVAR_LIMIT["moderate"]


@pytest.mark.parametrize("legacy", ["defensive", "balanced", "moderate_aggressive", "growth"])
def test_profile_cvar_limit_does_not_have_mandate_ladder(legacy: str) -> None:
    assert resolve_profile_cvar_limit(legacy) == PROFILE_CVAR_LIMIT["moderate"]
