"""Regime-Aware (research codename COMBO) — Task 1: ``regime_aware`` objective +
diagnostics fields.

Schema-only contract tests (no DB / no solver): the ``"regime_aware"`` objective
is accepted by ``OptimizeRequest`` with no extra required client-side CVaR field
(bands and hard CVaR derive from the calibrated profile), and ``DiagnosticsOut``
carries the additive regime fields
(``quadrant`` / ``class_bands`` / ``haven_tilt`` / ``beta_cap``; the legacy
``combined_regime`` was retired in Task 9 — the orthogonal quadrant/gate model).
"""

from app.schemas.builder import DiagnosticsOut, OptimizeRequest


def test_regime_aware_is_valid_objective() -> None:
    req = OptimizeRequest.model_validate(
        {
            "assets": [
                {"kind": "equity", "ticker": "AAA"},
                {"kind": "equity", "ticker": "BBB"},
            ],
            "objective": "regime_aware",
        }
    )
    assert req.objective == "regime_aware"


def test_regime_aware_needs_no_extra_required_field() -> None:
    """regime_aware derives bands and CVaR from the calibrated profile, so no
    client ``cvar_limit`` (unlike ``max_return_cvar``) is required."""
    req = OptimizeRequest.model_validate(
        {
            "assets": [
                {"kind": "fund", "id": "00000000-0000-0000-0000-000000000001"},
                {"kind": "fund", "id": "00000000-0000-0000-0000-000000000002"},
            ],
            "objective": "regime_aware",
        }
    )
    assert req.objective == "regime_aware"
    assert req.cvar_limit is None
    assert req.profile == "moderate"


def test_regime_aware_rejects_client_cvar_limit() -> None:
    import pytest
    from pydantic import ValidationError

    with pytest.raises(ValidationError, match="CVaR is calibrated by profile"):
        OptimizeRequest.model_validate(
            {
                "assets": [
                    {"kind": "fund", "id": "00000000-0000-0000-0000-000000000001"},
                    {"kind": "fund", "id": "00000000-0000-0000-0000-000000000002"},
                ],
                "objective": "regime_aware",
                "profile": "conservative",
                "cvar_limit": 0.01,
            }
        )


def test_diagnostics_has_regime_fields() -> None:
    d = DiagnosticsOut(
        n_obs=10,
        status="optimal",
        quadrant="SLOWDOWN",
        class_bands={"equity": [0.26, 0.50]},
        haven_tilt={"GLD": 0.3, "BIL": 0.3},
    )
    assert d.quadrant == "SLOWDOWN"
    assert d.class_bands is not None and d.class_bands["equity"] == [0.26, 0.50]
    assert d.haven_tilt is not None and d.haven_tilt["GLD"] == 0.3


def test_diagnostics_regime_fields_default_none() -> None:
    """The regime fields are additive/optional — absent on the non-regime paths."""
    d = DiagnosticsOut(n_obs=5, status="optimal")
    assert d.quadrant is None
    assert d.class_bands is None
    assert d.haven_tilt is None


def test_diagnostics_has_no_combined_regime_field() -> None:
    from app.schemas.builder import DiagnosticsOut

    assert "combined_regime" not in DiagnosticsOut.model_fields


def test_diagnostics_exposes_beta_cap_field() -> None:
    # The aggregate portfolio-beta cap is enforced by the compiled two-level book.
    from app.schemas.builder import DiagnosticsOut

    assert "beta_cap" in DiagnosticsOut.model_fields


def test_macro_quadrant_out_has_no_combined_regime_field() -> None:
    from app.schemas.macro import MacroQuadrantOut

    assert "combined_regime" not in MacroQuadrantOut.model_fields
