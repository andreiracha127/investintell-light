"""COMBO S3: per-profile 7-sleeve mandate centers + effective bands.

Ports the harness PROFILE_CENTERS (7 sleeves x 4 band-states x 3 profiles) and the
quadrant -> band-state map onto the production band-clamping machinery
(``compute_effective_band`` + ``HW_SCALE``). The bands are the regime_aware
Level-1 envelope; the profile differentiation lives here (and in gamma).
"""

import pytest

from app.services import taa_bands as tb


def test_band_state_from_quadrant_map() -> None:
    assert tb.band_state_from_quadrant("RECOVERY") == "RISK_ON"
    assert tb.band_state_from_quadrant("") == "RISK_ON"
    assert tb.band_state_from_quadrant("EXPANSION") == "INFLATION"
    assert tb.band_state_from_quadrant("SLOWDOWN") == "SLOWDOWN"
    assert tb.band_state_from_quadrant("CONTRACTION") == "CONTRACTION"
    assert tb.band_state_from_quadrant("nonsense") == "SLOWDOWN"  # unknown -> mildly defensive


@pytest.mark.parametrize("profile", ["aggressive", "moderate", "conservative"])
@pytest.mark.parametrize("state", ["RISK_ON", "INFLATION", "SLOWDOWN", "CONTRACTION"])
def test_normalized_centers_sum_to_one(profile: str, state: str) -> None:
    centers = tb.normalized_profile_centers(profile, state)
    assert set(centers) == set(tb.SLEEVE_GROUPS)
    assert abs(sum(centers.values()) - 1.0) < 1e-9


@pytest.mark.parametrize("profile", ["aggressive", "moderate", "conservative"])
@pytest.mark.parametrize("state", ["RISK_ON", "INFLATION", "SLOWDOWN", "CONTRACTION"])
def test_profile_sleeve_bands_within_ips(profile: str, state: str) -> None:
    bands = tb.profile_sleeve_bands(profile, state)
    assert set(bands) == set(tb.SLEEVE_GROUPS)
    for g, (lo, hi) in bands.items():
        ips_lo, ips_hi = tb.SLEEVE_IPS_BOUNDS[g]
        assert lo <= hi
        assert lo >= ips_lo - 1e-9
        assert hi <= ips_hi + 1e-9


def test_profile_sleeve_bands_parity_with_harness() -> None:
    # aggressive RISK_ON equity: center 0.33 (already sums to 1), hw 0.08,
    # half = 0.08*1.5 = 0.12 -> (0.21, 0.45) clamped to IPS (0,1).
    bands = tb.profile_sleeve_bands("aggressive", "RISK_ON")
    lo, hi = bands["equity"]
    assert lo == pytest.approx(0.21, abs=1e-6)
    assert hi == pytest.approx(0.45, abs=1e-6)
    # thematic: center 0.08, hw 0.05, half 0.075 -> (0.005, 0.155), IPS (0, 0.30)
    tlo, thi = bands["thematic"]
    assert tlo == pytest.approx(0.005, abs=1e-6)
    assert thi == pytest.approx(0.155, abs=1e-6)


def test_profile_centers_differentiate_equity() -> None:
    # The mandate ladder: aggressive holds more equity than conservative in RISK_ON.
    agg = tb.normalized_profile_centers("aggressive", "RISK_ON")
    con = tb.normalized_profile_centers("conservative", "RISK_ON")
    assert agg["equity"] > con["equity"]
    assert con["fixed_income"] > agg["fixed_income"]


def test_unknown_profile_rejected() -> None:
    with pytest.raises(KeyError):
        tb.normalized_profile_centers("wildly_unknown", "RISK_ON")
