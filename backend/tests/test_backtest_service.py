"""Service-level walk-forward backtest orchestration.

The DB loader is stubbed at its canonical module (app.optimizer.data); the
optimizer engine and the pure assemble stay LIVE so the happy path exercises
the real per-fold re-optimization end to end.
"""

import datetime as dt
import uuid
from typing import Any

import numpy as np
import pandas as pd
import pytest

from app.optimizer import data as optimizer_data
from app.schemas.backtest import WalkForwardRequest, WalkForwardResponse
from app.services import backtest as backtest_service
from app.services.backtest import BacktestError, _solve_fn_for

_FUND_IDS = [uuid.UUID(f"00000000-0000-0000-0000-00000000000{i}") for i in range(1, 6)]


def _fund(i: int) -> dict[str, str]:
    return {"kind": "fund", "id": str(_FUND_IDS[i])}


def _stub_returns(monkeypatch: pytest.MonkeyPatch, n_obs: int = 600) -> None:
    async def fake_load(
        session: Any,
        assets: list[optimizer_data.AssetRef],
        window_days: int | None = None,
        today: dt.date | None = None,
    ) -> pd.DataFrame:
        rng = np.random.default_rng(5)
        index = pd.bdate_range("2018-01-02", periods=n_obs)
        return pd.DataFrame(
            {ref.label: rng.normal(0.0004, 0.009 + 0.001 * i, n_obs)
             for i, ref in enumerate(assets)},
            index=index,
        )

    monkeypatch.setattr(optimizer_data, "load_aligned_returns", fake_load)


def test_solve_fn_min_cvar_is_long_only_sum_one() -> None:
    rng = np.random.default_rng(0)
    train = rng.normal(0.0005, 0.01, (300, 3))
    fn = _solve_fn_for("min_cvar", cap=0.5, min_weight=None)
    w = fn(train)
    assert abs(float(w.sum()) - 1.0) < 1e-6
    assert (w >= -1e-9).all() and (w <= 0.5 + 1e-6).all()


def test_solve_fn_min_vol_uses_covariance() -> None:
    rng = np.random.default_rng(1)
    train = rng.normal(0.0, 0.01, (300, 4))
    fn = _solve_fn_for("min_vol", cap=0.4, min_weight=None)
    w = fn(train)
    assert abs(float(w.sum()) - 1.0) < 1e-6


def test_solve_fn_bl_utility_is_rejected() -> None:
    with pytest.raises(BacktestError, match="bl_utility is not backtestable"):
        _solve_fn_for("bl_utility", cap=0.25, min_weight=None)


async def test_run_min_cvar_happy_path(monkeypatch: pytest.MonkeyPatch) -> None:
    _stub_returns(monkeypatch)
    # cap=0.5 is required for feasibility: the engine guard rejects the default
    # cap (0.25) on 3 assets because 0.25*3=0.75 < 1 (can't be fully invested).
    payload = WalkForwardRequest.model_validate(
        {"assets": [_fund(0), _fund(1), _fund(2)], "objective": "min_cvar",
         "constraints": {"cap": 0.5}}
    )
    resp = await backtest_service.run_walk_forward_backtest(None, payload)
    assert isinstance(resp, WalkForwardResponse)
    assert resp.params.objective == "min_cvar"
    assert resp.params.n_obs == 600
    assert resp.params.n_splits_computed == 5
    assert len(resp.folds) == 5
    assert resp.params.cost_bps == 10.0
    assert 0 <= resp.positive_folds <= 5
    assert all(f.cvar_95 >= 0 for f in resp.folds)
    assert all(f.max_drawdown <= 0 for f in resp.folds)


async def test_run_maps_insufficient_common_history_to_backtest_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fake_load(session: Any, assets: Any, **kwargs: Any) -> pd.DataFrame:
        raise ValueError("insufficient common history: 120 overlapping observations")

    monkeypatch.setattr(optimizer_data, "load_aligned_returns", fake_load)
    payload = WalkForwardRequest.model_validate(
        {"assets": [_fund(0), _fund(1)], "objective": "min_cvar"}
    )
    with pytest.raises(BacktestError, match="insufficient common history"):
        await backtest_service.run_walk_forward_backtest(None, payload)


async def test_run_maps_short_window_to_backtest_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # 300 obs cannot support 5 folds x 63 test after a 252 train minimum; the
    # loader stub bypasses MIN_COMMON_OBS so the analytics guard fires.
    _stub_returns(monkeypatch, n_obs=300)
    payload = WalkForwardRequest.model_validate(
        {"assets": [_fund(0), _fund(1)], "objective": "min_cvar",
         "n_splits": 5, "test_size": 63, "min_train_size": 252}
    )
    with pytest.raises(BacktestError, match="insufficient history"):
        await backtest_service.run_walk_forward_backtest(None, payload)
