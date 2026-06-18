"""Tests for POST /monte-carlo/portfolio.

The DB loader is stubbed at app.optimizer.data; the pure MC core stays live.
The session dependency is overridden (no live DB, no Tiingo - the portfolio
route reads only the data-lake via the loader).
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

_FUND_IDS = [uuid.UUID(f"00000000-0000-0000-0000-00000000000{i}") for i in range(1, 4)]


def _client() -> AsyncClient:
    app = create_app()
    app.dependency_overrides[get_session] = lambda: None
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


def _fund(i: int) -> dict[str, str]:
    return {"kind": "fund", "id": str(_FUND_IDS[i])}


def _stub_frame(monkeypatch: pytest.MonkeyPatch, n_obs: int = 500) -> None:
    async def fake_load(
        session: Any,
        assets: list[optimizer_data.AssetRef],
        window_days: int | None = None,
        today: dt.date | None = None,
    ) -> pd.DataFrame:
        rng = np.random.default_rng(17)
        index = pd.bdate_range("2018-01-02", periods=n_obs)
        return pd.DataFrame(
            {
                ref.label: rng.normal(0.0004, 0.009 + 0.001 * i, n_obs)
                for i, ref in enumerate(assets)
            },
            index=index,
        )

    monkeypatch.setattr(optimizer_data, "load_aligned_returns", fake_load)


async def test_portfolio_happy_path_shape(monkeypatch: pytest.MonkeyPatch) -> None:
    _stub_frame(monkeypatch)
    payload = {
        "positions": [
            {"asset": _fund(0), "weight": 0.6},
            {"asset": _fund(1), "weight": 0.4},
        ],
        "statistic": "return",
        "n_simulations": 2000,
        "seed": 7,
    }
    async with _client() as client:
        response = await client.post("/monte-carlo/portfolio", json=payload)
    assert response.status_code == 200, response.text
    body = response.json()
    assert set(body) == {
        "params",
        "percentiles",
        "mean",
        "median",
        "std",
        "historical_value",
        "historical_horizon_days",
        "historical_percentile_rank",
        "confidence_bars",
        "degraded",
        "degraded_reason",
    }
    assert body["params"]["n_assets"] == 2
    assert "ticker" not in body["params"]
    assert body["confidence_bars"][0]["horizon"] == "1Y"
    assert set(body["percentiles"].keys()) == {
        "1st",
        "5th",
        "10th",
        "25th",
        "50th",
        "75th",
        "90th",
        "95th",
        "99th",
    }


async def test_portfolio_is_deterministic_under_seed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _stub_frame(monkeypatch)
    payload = {
        "positions": [
            {"asset": _fund(0), "weight": 0.5},
            {"asset": _fund(1), "weight": 0.5},
        ],
        "statistic": "max_drawdown",
        "n_simulations": 1500,
        "seed": 5,
    }
    async with _client() as client:
        a = (await client.post("/monte-carlo/portfolio", json=payload)).json()
        b = (await client.post("/monte-carlo/portfolio", json=payload)).json()
    assert a["percentiles"] == b["percentiles"]


async def test_portfolio_insufficient_common_history_422(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fake_load(session: Any, assets: Any, **kwargs: Any) -> pd.DataFrame:
        raise ValueError("insufficient common history: 120 overlapping observations")

    monkeypatch.setattr(optimizer_data, "load_aligned_returns", fake_load)
    payload = {
        "positions": [
            {"asset": _fund(0), "weight": 0.5},
            {"asset": _fund(1), "weight": 0.5},
        ]
    }
    async with _client() as client:
        response = await client.post("/monte-carlo/portfolio", json=payload)
    assert response.status_code == 422
    assert "insufficient common history" in response.json()["detail"]


async def test_portfolio_bad_weight_is_pydantic_422() -> None:
    payload = {
        "positions": [
            {"asset": _fund(0), "weight": 0.0},
            {"asset": _fund(1), "weight": 1.0},
        ]
    }
    async with _client() as client:
        response = await client.post("/monte-carlo/portfolio", json=payload)
    assert response.status_code == 422  # weight gt=0


async def test_portfolio_requires_two_positions_422() -> None:
    payload = {"positions": [{"asset": _fund(0), "weight": 1.0}]}
    async with _client() as client:
        response = await client.post("/monte-carlo/portfolio", json=payload)
    assert response.status_code == 422  # min_length=2
