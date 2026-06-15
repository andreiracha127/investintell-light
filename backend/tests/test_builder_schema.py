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
