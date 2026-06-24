import math

import pytest

from app.services import quadrant_policy as qp


def test_constants_shape() -> None:
    assert qp.STRUCTURAL_SLEEVES == (
        "cash", "equity", "fixed_income", "thematic",
        "alternatives", "gold", "long_short",
    )
    assert len(qp.FIXED_INCOME_BUCKETS) == 6
    assert qp.QUADRANTS == ("recovery", "expansion", "slowdown", "contraction")
    assert qp.PROFILES == ("aggressive", "moderate", "conservative")
    assert qp.POLICY_VERSION == "combo_policy_us_v1.0"


def test_twelve_policies_present_and_versioned() -> None:
    assert set(qp.QUADRANT_POLICIES) == set(qp.PROFILES)
    count = 0
    for profile in qp.PROFILES:
        assert set(qp.QUADRANT_POLICIES[profile]) == set(qp.QUADRANTS)
        for quadrant in qp.QUADRANTS:
            pol = qp.QUADRANT_POLICIES[profile][quadrant]
            assert isinstance(pol, qp.QuadrantPolicy)
            assert pol.policy_version == qp.POLICY_VERSION
            assert set(pol.center) == set(qp.STRUCTURAL_SLEEVES)
            assert set(pol.half_width) == set(qp.STRUCTURAL_SLEEVES)
            count += 1
    assert count == 12


def test_every_center_sums_to_one() -> None:
    for profile in qp.PROFILES:
        for quadrant in qp.QUADRANTS:
            pol = qp.QUADRANT_POLICIES[profile][quadrant]
            total = sum(pol.center.values())
            assert math.isclose(total, 1.0, abs_tol=1e-6), (
                f"{profile}/{quadrant} sums to {total}"
            )


def test_fixed_income_sub_budgets_empty_in_v1() -> None:
    for profile in qp.PROFILES:
        for quadrant in qp.QUADRANTS:
            assert qp.QUADRANT_POLICIES[profile][quadrant].fixed_income_sub_budgets == {}


def test_policy_bands_derives_lo_hi_clamped() -> None:
    pol = qp.QUADRANT_POLICIES["moderate"]["recovery"]
    bands = qp.policy_bands(pol)
    assert set(bands) == set(qp.STRUCTURAL_SLEEVES)
    for g in qp.STRUCTURAL_SLEEVES:
        lo, hi = bands[g]
        c, hw = pol.center[g], pol.half_width[g]
        assert lo == pytest.approx(max(0.0, c - hw))
        assert hi == pytest.approx(min(1.0, c + hw))
        assert 0.0 <= lo <= c <= hi <= 1.0
