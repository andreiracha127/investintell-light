import dataclasses
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


def test_section15_band_invariants_on_materialized_policies() -> None:
    """Spec §15 invariants on the MATERIALIZED policies, for ALL 12 × 7 sleeves.

    This is exactly the set Task 2's startup validator enforces. The materialized
    half_widths must satisfy the *raw* relationship 0 ≤ center − half_width
    (clamping inside policy_bands does NOT make the seed legal — the validator
    checks the raw center/half_width relationship, not the clamped band).
    """
    for profile in qp.PROFILES:
        for quadrant in qp.QUADRANTS:
            pol = qp.QUADRANT_POLICIES[profile][quadrant]
            tag = f"{profile}/{quadrant}"

            # centers: each in [0,1] and sum to 1
            for s in qp.STRUCTURAL_SLEEVES:
                c = pol.center[s]
                assert 0.0 <= c <= 1.0, f"{tag} {s} center={c} out of [0,1]"
            assert math.isclose(
                sum(pol.center.values()), 1.0, abs_tol=1e-6
            ), f"{tag} centers do not sum to 1"

            lo_sum = 0.0
            hi_sum = 0.0
            for s in qp.STRUCTURAL_SLEEVES:
                c = pol.center[s]
                hw = pol.half_width[s]
                lo = c - hw
                hi = c + hw
                # the exact relationship that was violated by the §18/§19 seeds:
                assert lo >= -1e-12, f"{tag} {s} center−half_width={lo} < 0"
                assert hi <= 1.0 + 1e-12, f"{tag} {s} center+half_width={hi} > 1"
                assert 0.0 <= lo <= c <= hi <= 1.0, (
                    f"{tag} {s} violates 0≤lo≤center≤hi≤1 "
                    f"(center={c}, half_width={hw})"
                )
                lo_sum += lo
                hi_sum += hi

            assert lo_sum <= 1.0 + 1e-9, f"{tag} Σlo={lo_sum} > 1"
            assert hi_sum >= 1.0 - 1e-9, f"{tag} Σhi={hi_sum} < 1"

            risk = pol.center["equity"] + pol.center["thematic"]
            assert risk <= pol.risk_assets_cap + 1e-9, (
                f"{tag} equity+thematic={risk} > risk_assets_cap={pol.risk_assets_cap}"
            )
            defensive = (
                pol.center["cash"]
                + pol.center["fixed_income"]
                + pol.center["gold"]
                + pol.center["long_short"]
            )
            assert defensive >= pol.defensive_floor - 1e-9, (
                f"{tag} cash+fixed_income+gold+long_short={defensive} "
                f"< defensive_floor={pol.defensive_floor}"
            )


def test_validate_passes_on_shipped_policies() -> None:
    qp.validate_quadrant_policies()  # must not raise


def test_validate_rejects_center_not_summing_one() -> None:
    pol = qp.QUADRANT_POLICIES["moderate"]["recovery"]
    bad_center = dict(pol.center)
    bad_center["cash"] += 0.05  # now sums to 1.05
    bad = dataclasses.replace(pol, center=bad_center)
    policies = {"moderate": {"recovery": bad}}
    with pytest.raises(qp.PolicyError, match="sum to 1"):
        qp.validate_quadrant_policies(policies)


def test_validate_rejects_band_out_of_unit_interval() -> None:
    pol = qp.QUADRANT_POLICIES["aggressive"]["recovery"]
    bad_hw = dict(pol.half_width)
    bad_hw["equity"] = 0.50  # center 0.33 → lo = -0.17
    bad = dataclasses.replace(pol, half_width=bad_hw)
    policies = {"aggressive": {"recovery": bad}}
    with pytest.raises(qp.PolicyError, match="lo"):
        qp.validate_quadrant_policies(policies)


def test_validate_rejects_risk_assets_cap_breach() -> None:
    pol = qp.QUADRANT_POLICIES["aggressive"]["recovery"]  # equity .33 + thematic .08 = .41
    bad = dataclasses.replace(pol, risk_assets_cap=0.30)  # < .41
    policies = {"aggressive": {"recovery": bad}}
    with pytest.raises(qp.PolicyError, match="risk_assets_cap"):
        qp.validate_quadrant_policies(policies)


def test_validate_rejects_defensive_floor_breach() -> None:
    pol = qp.QUADRANT_POLICIES["moderate"]["recovery"]
    # cash+fi+gold+ls = .10+.38+.10+.08 = .66; demand .80 → breach
    bad = dataclasses.replace(pol, defensive_floor=0.80)
    policies = {"moderate": {"recovery": bad}}
    with pytest.raises(qp.PolicyError, match="defensive_floor"):
        qp.validate_quadrant_policies(policies)


def test_validate_rejects_missing_policy() -> None:
    policies = {"moderate": {"recovery": qp.QUADRANT_POLICIES["moderate"]["recovery"]}}
    with pytest.raises(qp.PolicyError, match="missing"):
        qp.validate_quadrant_policies(policies)


def test_validate_rejects_missing_sleeve() -> None:
    pol = qp.QUADRANT_POLICIES["moderate"]["recovery"]
    bad_center = dict(pol.center)
    del bad_center["gold"]  # drop a structural sleeve from center
    bad = dataclasses.replace(pol, center=bad_center)
    policies = {"moderate": {"recovery": bad}}
    with pytest.raises(qp.PolicyError, match="STRUCTURAL_SLEEVES"):
        qp.validate_quadrant_policies(policies)


def test_validate_accepts_sum_lo_at_boundary() -> None:
    # Build a policy whose Σlo == 1 (boundary, must pass). center is valid (sum 1),
    # half_widths 0 so lo == center for every sleeve → Σlo == Σcenter == 1.0.
    # The caps must also be consistent with these uniform centers, so the ONLY thing
    # under test is the Σlo boundary (not risk_assets_cap / defensive_floor).
    pol = qp.QUADRANT_POLICIES["conservative"]["contraction"]
    bad_center = {g: 1.0 / 7 for g in qp.STRUCTURAL_SLEEVES}
    bad_hw = {g: 0.0 for g in qp.STRUCTURAL_SLEEVES}
    bad_center["fixed_income"] = 1.0 / 7 + 1e-3
    bad_center["cash"] = 1.0 / 7 - 1e-3  # keep sum 1
    bad = dataclasses.replace(
        pol,
        center=bad_center,
        half_width=bad_hw,
        risk_assets_cap=1.0,    # uniform equity+thematic = 2/7 ≈ 0.286, allow it
        defensive_floor=0.0,    # uniform defensive sum is fine; don't constrain it
    )
    # Σlo == 1.0 (lo == center, Σcenter == 1) → boundary must PASS (no raise). Tested
    # via the per-policy validator: validate_quadrant_policies enforces all-12-present,
    # so a single-policy dict would (correctly) raise "missing" before we could observe
    # the Σlo boundary in isolation.
    qp._validate_one("conservative", "contraction", bad)  # must not raise


def test_validate_full_default_set_is_complete_and_valid() -> None:
    # The startup call (no args) validates the real 12 and enforces completeness.
    qp.validate_quadrant_policies(qp.QUADRANT_POLICIES)
