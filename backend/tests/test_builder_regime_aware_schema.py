"""Regime-Aware (research codename COMBO) — Task 1: ``regime_aware`` objective +
diagnostics fields.

Schema-only contract tests (no DB / no solver): the ``"regime_aware"`` objective
is accepted by ``OptimizeRequest`` with no extra required field (bands derive
from the regime), and ``DiagnosticsOut`` carries the additive regime fields
(``quadrant`` / ``combined_regime`` / ``class_bands`` / ``haven_tilt``).
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
    """regime_aware derives its bands from the regime, so no ``cvar_limit``
    (unlike ``max_return_cvar``) and no ``block_budgets`` are required."""
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


def test_diagnostics_has_regime_fields() -> None:
    d = DiagnosticsOut(
        n_obs=10,
        status="optimal",
        quadrant="SLOWDOWN",
        combined_regime="STAG_GOLD",
        class_bands={"equity": [0.26, 0.50]},
        haven_tilt={"GLD": 0.3, "BIL": 0.3},
    )
    assert d.quadrant == "SLOWDOWN"
    assert d.combined_regime == "STAG_GOLD"
    assert d.class_bands is not None and d.class_bands["equity"] == [0.26, 0.50]
    assert d.haven_tilt is not None and d.haven_tilt["GLD"] == 0.3


def test_diagnostics_regime_fields_default_none() -> None:
    """The regime fields are additive/optional — absent on the non-regime paths."""
    d = DiagnosticsOut(n_obs=5, status="optimal")
    assert d.quadrant is None
    assert d.combined_regime is None
    assert d.class_bands is None
    assert d.haven_tilt is None
