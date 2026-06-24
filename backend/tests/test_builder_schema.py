"""Schema-level tests for OptimizeRequest — window-gate removal.

The 2-year window gate is removed: ``window_days`` defaults to None (use the
full nav_timeseries history). An explicit int still narrows the window.
"""

import uuid

from app.schemas.builder import OptimizeRequest

_A = str(uuid.UUID("00000000-0000-0000-0000-000000000001"))
_B = str(uuid.UUID("00000000-0000-0000-0000-000000000002"))


def _assets() -> list[dict[str, str]]:
    return [{"kind": "fund", "id": _A}, {"kind": "fund", "id": _B}]


def test_window_days_defaults_to_full_history() -> None:
    """No window_days → None (full history; the 2-year gate is gone)."""
    req = OptimizeRequest(assets=_assets())
    assert req.window_days is None


def test_window_days_none_is_valid() -> None:
    req = OptimizeRequest(assets=_assets(), window_days=None)
    assert req.window_days is None


def test_window_days_accepts_explicit_value() -> None:
    req = OptimizeRequest(assets=_assets(), window_days=730)
    assert req.window_days == 730


def test_constraints_accepts_block_budgets() -> None:
    from app.schemas.builder import ConstraintsIn

    c = ConstraintsIn(block_budgets=[{"asset_class": "equity", "lo": 0.0, "hi": 0.3}])
    assert c.block_budgets is not None
    assert c.block_budgets[0].asset_class == "equity"
    assert c.block_budgets[0].hi == 0.3


def test_constraints_block_budget_rejects_lo_above_hi() -> None:
    import pytest
    from pydantic import ValidationError

    from app.schemas.builder import ConstraintsIn

    with pytest.raises(ValidationError):
        ConstraintsIn(block_budgets=[{"asset_class": "equity", "lo": 0.5, "hi": 0.2}])


def test_optimize_request_accepts_turnover_and_current_weights() -> None:
    req = OptimizeRequest(
        assets=_assets(),
        turnover_lambda=2.0,
        current_weights={f"fund:{_A}": 0.6, f"fund:{_B}": 0.4},
    )
    assert req.turnover_lambda == 2.0
    assert req.current_weights == {f"fund:{_A}": 0.6, f"fund:{_B}": 0.4}


def test_optimize_request_turnover_requires_current_weights() -> None:
    import pytest
    from pydantic import ValidationError

    with pytest.raises(ValidationError, match="current_weights"):
        OptimizeRequest(assets=_assets(), turnover_lambda=2.0)


def test_objective_accepts_max_return_cvar() -> None:
    req = OptimizeRequest(
        assets=_assets(), objective="max_return_cvar", cvar_limit=0.05,
    )
    assert req.objective == "max_return_cvar"
    assert req.cvar_limit == 0.05


def test_max_return_cvar_requires_cvar_limit() -> None:
    import pytest
    from pydantic import ValidationError

    with pytest.raises(ValidationError, match="cvar_limit"):
        OptimizeRequest(
            assets=_assets(), objective="max_return_cvar",
        )


def test_views_with_universe_is_rejected() -> None:
    """Views reference specific assets; a universe selects them — incompatible."""
    import pytest
    from pydantic import ValidationError

    with pytest.raises(ValidationError, match="views cannot be combined"):
        OptimizeRequest(
            universe={},
            objective="max_return_cvar",
            cvar_limit=0.05,
            views=[{"type": "absolute", "asset": {"kind": "fund", "id": _A}, "q": 0.1}],
        )


def test_optimize_request_profile_defaults_to_moderate() -> None:
    req = OptimizeRequest(assets=_assets())
    assert req.profile == "moderate"


def test_optimize_request_accepts_canonical_profile() -> None:
    req = OptimizeRequest(assets=_assets(), profile="aggressive")
    assert req.profile == "aggressive"


def test_optimize_request_rejects_noncanonical_profile() -> None:
    import pytest
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        OptimizeRequest(assets=_assets(), profile="moderate_aggressive")


def test_regime_aware_rejects_client_cvar_limit_override() -> None:
    import pytest
    from pydantic import ValidationError

    with pytest.raises(ValidationError, match="CVaR is calibrated by profile"):
        OptimizeRequest(
            assets=_assets(), objective="regime_aware", profile="moderate", cvar_limit=0.05
        )


def test_diagnostics_out_view_consistency_defaults_to_none() -> None:
    from app.schemas.builder import DiagnosticsOut

    diag = DiagnosticsOut(n_obs=10, status="optimal")
    assert diag.view_consistency is None


def test_max_return_cvar_allowed_in_broad_universe() -> None:
    """BL over the broad-universe path is now permitted (equilibrium prior)."""
    from app.schemas.builder import OptimizeRequest

    req = OptimizeRequest.model_validate(
        {
            "universe": {"broad_universe": True, "max_positions": 20},
            "objective": "max_return_cvar",
            "cvar_limit": 0.02,
        }
    )
    assert req.objective == "max_return_cvar"
    assert req.cvar_limit == 0.02


def test_max_return_cvar_still_requires_cvar_limit_in_broad_universe() -> None:
    """Dropping the broad-universe block must NOT drop the cvar_limit guard."""
    import pytest
    from pydantic import ValidationError

    from app.schemas.builder import OptimizeRequest

    with pytest.raises(ValidationError, match="cvar_limit"):
        OptimizeRequest.model_validate(
            {"universe": {"broad_universe": True}, "objective": "max_return_cvar"}
        )


def test_broad_universe_accepts_min_cvar_default() -> None:
    from app.schemas.builder import OptimizeRequest

    req = OptimizeRequest.model_validate(
        {"universe": {"broad_universe": True, "max_positions": 25}}
    )
    assert req.universe is not None
    assert req.universe.broad_universe is True
    assert req.universe.max_positions == 25
    assert req.objective == "min_cvar"


def test_bl_utility_allowed_in_broad_universe() -> None:
    """bl_utility over the broad-universe path is now permitted (no views)."""
    from app.schemas.builder import OptimizeRequest

    req = OptimizeRequest.model_validate(
        {"universe": {"broad_universe": True, "max_positions": 20}, "objective": "bl_utility"}
    )
    assert req.objective == "bl_utility"
    assert req.universe is not None
    assert req.universe.broad_universe is True


def test_views_still_rejected_with_broad_universe() -> None:
    """views + universe stays rejected even for BL objectives in broad mode."""
    import pytest
    from pydantic import ValidationError

    from app.schemas.builder import OptimizeRequest

    with pytest.raises(ValidationError, match="views cannot be combined"):
        OptimizeRequest.model_validate(
            {
                "universe": {"broad_universe": True},
                "objective": "bl_utility",
                "views": [
                    {"type": "absolute", "asset": {"kind": "fund", "id": _A}, "q": 0.1}
                ],
            }
        )


def test_bl_utility_accepts_ranked_universe() -> None:
    from app.schemas.builder import OptimizeRequest

    req = OptimizeRequest.model_validate(
        {"universe": {"broad_universe": False}, "objective": "bl_utility"}
    )
    assert req.objective == "bl_utility"
    assert req.universe is not None
    assert req.universe.broad_universe is False
