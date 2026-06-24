"""Task 10 — COMBO startup validation hook (spec §37).

The service must REFUSE TO BOOT if any of the 12 QuadrantPolicies is invalid, the
gate shape/ladder collapses, or a retired legacy symbol creeps back onto the
production module. These tests cover the happy path (shipped config validates) and
one fail-loud case per validation class.
"""
import pytest

from app.core import policy_startup as ps


def test_validate_combo_startup_passes_on_shipped_config() -> None:
    ps.validate_combo_startup()  # must not raise


def test_validate_combo_startup_rejects_invalid_policies(monkeypatch) -> None:
    import dataclasses

    from app.services import quadrant_policy as qp

    pol = qp.QUADRANT_POLICIES["moderate"]["recovery"]
    bad_center = dict(pol.center)
    bad_center["cash"] += 0.10
    bad = dataclasses.replace(pol, center=bad_center)
    broken = {p: dict(qp.QUADRANT_POLICIES[p]) for p in qp.PROFILES}
    broken["moderate"]["recovery"] = bad
    monkeypatch.setattr(qp, "QUADRANT_POLICIES", broken)
    with pytest.raises(ps.StartupValidationError):
        ps.validate_combo_startup()


def test_validate_combo_startup_rejects_surviving_legacy_symbol(monkeypatch) -> None:
    from app.services import taa_bands

    monkeypatch.setattr(
        taa_bands, "combined_regime", lambda *a, **k: "RISK_ON", raising=False
    )
    with pytest.raises(ps.StartupValidationError, match="combined_regime"):
        ps.validate_combo_startup()


def test_validate_combo_startup_rejects_ladder_collapse(monkeypatch) -> None:
    from app.optimizer import gate_overlay as go

    same = go.ProfileGatePolicy(intensity=0.7, bl_view_confidence_multiplier=0.0)
    monkeypatch.setattr(
        go,
        "PROFILE_GATE_POLICIES",
        {"aggressive": same, "moderate": same, "conservative": same},
    )
    with pytest.raises(ps.StartupValidationError, match="ladder"):
        ps.validate_combo_startup()
