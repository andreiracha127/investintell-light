"""Tests for POST /backtest/walk-forward (app/api/routes/backtest.py).

The DB loader is stubbed at app.optimizer.data; the optimizer + pure backtest
math stay LIVE so the happy path runs the real per-fold re-optimization.
"""

import datetime as dt
import uuid
from typing import Any

import numpy as np
import pandas as pd
import pytest
from httpx import ASGITransport, AsyncClient

from app.core.db import get_session
from app.main import create_app
from app.optimizer import data as optimizer_data

_FUND_IDS = [uuid.UUID(f"00000000-0000-0000-0000-00000000000{i}") for i in range(1, 6)]


def _client() -> AsyncClient:
    app = create_app()
    app.dependency_overrides[get_session] = lambda: None
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


def _fund(i: int) -> dict[str, str]:
    return {"kind": "fund", "id": str(_FUND_IDS[i])}


def _stub_returns(monkeypatch: pytest.MonkeyPatch, n_obs: int = 600) -> None:
    async def fake_load(
        session: Any,
        assets: list[optimizer_data.AssetRef],
        window_days: int | None = None,
        today: dt.date | None = None,
        *,
        convention: str = "log",
    ) -> pd.DataFrame:
        rng = np.random.default_rng(9)
        index = pd.bdate_range("2018-01-02", periods=n_obs)
        return pd.DataFrame(
            {ref.label: rng.normal(0.0004, 0.009 + 0.001 * i, n_obs)
             for i, ref in enumerate(assets)},
            index=index,
        )

    monkeypatch.setattr(optimizer_data, "load_aligned_returns", fake_load)


async def test_walk_forward_min_cvar_happy_path(monkeypatch: pytest.MonkeyPatch) -> None:
    _stub_returns(monkeypatch)
    payload = {"assets": [_fund(0), _fund(1), _fund(2)], "objective": "min_cvar",
               "constraints": {"cap": 0.5}}  # cap*n>=1 feasibility (default 0.25*3<1 is infeasible)
    async with _client() as client:
        response = await client.post("/backtest/walk-forward", json=payload)
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["params"]["objective"] == "min_cvar"
    assert body["params"]["n_splits_computed"] == 5
    assert len(body["folds"]) == 5
    assert 0 <= body["positive_folds"] <= 5
    assert all(f["cvar_95"] >= 0 for f in body["folds"])
    assert all(f["max_drawdown"] <= 0 for f in body["folds"])
    assert body["folds"][0]["turnover"] == pytest.approx(1.0, abs=1e-6)  # buy-in from cash


async def test_walk_forward_min_vol_happy_path(monkeypatch: pytest.MonkeyPatch) -> None:
    _stub_returns(monkeypatch)
    payload = {"assets": [_fund(i) for i in range(4)], "objective": "min_vol",
               "constraints": {"cap": 0.4}}
    async with _client() as client:
        response = await client.post("/backtest/walk-forward", json=payload)
    assert response.status_code == 200, response.text
    assert response.json()["params"]["objective"] == "min_vol"


async def test_insufficient_common_history_maps_to_422(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_load(session: Any, assets: Any, **kwargs: Any) -> pd.DataFrame:
        raise ValueError("insufficient common history: 120 overlapping observations")

    monkeypatch.setattr(optimizer_data, "load_aligned_returns", fake_load)
    payload = {"assets": [_fund(0), _fund(1)], "objective": "min_cvar"}
    async with _client() as client:
        response = await client.post("/backtest/walk-forward", json=payload)
    assert response.status_code == 422
    assert "insufficient common history" in response.json()["detail"]


async def test_short_window_maps_to_422(monkeypatch: pytest.MonkeyPatch) -> None:
    _stub_returns(monkeypatch, n_obs=300)
    payload = {"assets": [_fund(0), _fund(1)], "objective": "min_cvar"}
    async with _client() as client:
        response = await client.post("/backtest/walk-forward", json=payload)
    assert response.status_code == 422
    assert "insufficient history" in response.json()["detail"]


async def test_bl_utility_rejected_with_422(monkeypatch: pytest.MonkeyPatch) -> None:
    _stub_returns(monkeypatch)
    payload = {"assets": [_fund(0), _fund(1)], "objective": "bl_utility"}
    async with _client() as client:
        response = await client.post("/backtest/walk-forward", json=payload)
    assert response.status_code == 422
    assert "bl_utility is not backtestable" in response.json()["detail"]


async def test_walk_forward_max_return_cvar_equilibrium_happy_path(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _stub_returns(monkeypatch)

    async def fake_w_mkt(session: Any, assets: Any, labels: list[str]) -> np.ndarray:
        return np.full(len(labels), 1.0 / len(labels))

    # The route calls the service; patch _market_weights_for at the service module.
    from app.services import backtest as backtest_service

    monkeypatch.setattr(backtest_service, "_market_weights_for", fake_w_mkt)
    payload = {
        "assets": [_fund(0), _fund(1), _fund(2)],
        "objective": "max_return_cvar",
        "cvar_limit": 0.05,
        "constraints": {"cap": 0.6},
    }
    async with _client() as client:
        response = await client.post("/backtest/walk-forward", json=payload)
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["params"]["objective"] == "max_return_cvar"
    assert body["params"]["n_splits_computed"] == 5


async def test_walk_forward_max_return_cvar_missing_cvar_limit_422(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _stub_returns(monkeypatch)
    payload = {"assets": [_fund(0), _fund(1)], "objective": "max_return_cvar"}
    async with _client() as client:
        response = await client.post("/backtest/walk-forward", json=payload)
    assert response.status_code == 422


async def test_walk_forward_max_return_cvar_equities_422(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _stub_returns(monkeypatch)

    async def fake_mcap(session: Any, tickers: list[str]) -> dict[str, float | None]:
        return {ticker: None for ticker in tickers}

    monkeypatch.setattr(optimizer_data, "load_equity_market_cap", fake_mcap)
    payload = {
        "assets": [
            {"kind": "equity", "ticker": "SPY"},
            {"kind": "equity", "ticker": "AGG"},
        ],
        "objective": "max_return_cvar",
        "cvar_limit": 0.05,
        "constraints": {"cap": 0.6},
    }
    async with _client() as client:
        response = await client.post("/backtest/walk-forward", json=payload)
    assert response.status_code == 422
    assert "equities" in response.json()["detail"]


async def test_bad_n_splits_is_pydantic_422() -> None:
    payload = {"assets": [_fund(0), _fund(1)], "n_splits": 1}
    async with _client() as client:
        response = await client.post("/backtest/walk-forward", json=payload)
    assert response.status_code == 422  # Field(ge=2)


async def test_walk_forward_response_carries_oos_curve(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _stub_returns(monkeypatch)
    payload = {
        "assets": [_fund(0), _fund(1), _fund(2)],
        "objective": "min_cvar",
        "constraints": {"cap": 0.5},
    }
    async with _client() as client:
        response = await client.post("/backtest/walk-forward", json=payload)
    assert response.status_code == 200, response.text
    body = response.json()
    # One OOS point per observation across all folds (5 folds x 63 = 315).
    total_obs = sum(f["n_obs"] for f in body["folds"])
    assert len(body["oos_curve"]) == total_obs
    # Each point is a [iso_date, nav] 2-element array; nav is finite & positive.
    first = body["oos_curve"][0]
    assert isinstance(first, list) and len(first) == 2
    assert isinstance(first[0], str)  # ISO date
    assert float(first[1]) > 0
    # One boundary per fold; the first boundary == the first curve date.
    assert len(body["fold_boundaries"]) == len(body["folds"])
    assert body["fold_boundaries"][0] == first[0]
