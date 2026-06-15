"""Schema contract for POST /backtest/walk-forward."""

import uuid

import pytest
from pydantic import ValidationError

from app.schemas.backtest import (
    FoldMetricsOut,
    WalkForwardParams,
    WalkForwardRequest,
    WalkForwardResponse,
)


def _fund(i: int) -> dict[str, str]:
    return {"kind": "fund", "id": str(uuid.UUID(f"00000000-0000-0000-0000-00000000000{i}"))}


def test_request_defaults() -> None:
    req = WalkForwardRequest.model_validate(
        {"assets": [_fund(1), _fund(2)], "objective": "min_cvar"}
    )
    assert req.objective == "min_cvar"
    assert req.n_splits == 5
    assert req.gap == 2
    assert req.test_size == 63
    assert req.min_train_size == 252
    assert req.cost_bps == 10.0
    assert req.risk_free_annual == 0.0
    assert req.window_days is None
    assert req.constraints.cap == 0.25


def test_request_requires_two_assets() -> None:
    with pytest.raises(ValidationError):
        WalkForwardRequest.model_validate({"assets": [_fund(1)], "objective": "min_cvar"})


def test_request_rejects_bad_bounds() -> None:
    with pytest.raises(ValidationError):
        WalkForwardRequest.model_validate(
            {"assets": [_fund(1), _fund(2)], "n_splits": 1}  # ge=2
        )
    with pytest.raises(ValidationError):
        WalkForwardRequest.model_validate(
            {"assets": [_fund(1), _fund(2)], "cost_bps": -1.0}  # ge=0
        )


def test_response_round_trips() -> None:
    fold = FoldMetricsOut(
        fold=0, train_size=283, n_obs=63, sharpe=1.1, cvar_95=0.02,
        max_drawdown=-0.08, turnover=1.0, gross_return=0.03, net_return=0.029,
    )
    resp = WalkForwardResponse(
        folds=[fold],
        params=WalkForwardParams(
            objective="min_cvar", n_obs=600, n_splits_computed=5, gap=2,
            test_size=63, min_train_size=252, cost_bps=10.0,
        ),
        mean_sharpe=1.1, std_sharpe=0.0, positive_folds=1, mean_turnover=1.0,
    )
    dumped = resp.model_dump()
    assert dumped["folds"][0]["max_drawdown"] == -0.08
    assert dumped["positive_folds"] == 1
    assert dumped["params"]["objective"] == "min_cvar"
