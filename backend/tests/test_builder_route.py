"""Tests for POST /builder/optimize (app/api/routes/builder.py).

The data-loading layer is stubbed at its canonical module
(``app.optimizer.data``) — no live DB. The optimizer/BL math stays LIVE so
the happy paths exercise the real pipeline end to end.

422 contract covered: insufficient common history, unknown asset, views with
equities / funds without AUM, rank-deficient P.
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


def _fund_ref(i: int) -> dict[str, str]:
    return {"kind": "fund", "id": str(_FUND_IDS[i])}


def _stub_returns(monkeypatch: pytest.MonkeyPatch, n_obs: int = 500) -> None:
    async def fake_load(
        session: Any,
        assets: list[optimizer_data.AssetRef],
        window_days: int = 730,
        today: dt.date | None = None,
    ) -> pd.DataFrame:
        rng = np.random.default_rng(11)
        index = pd.bdate_range("2024-01-02", periods=n_obs)
        data = {
            ref.label: rng.normal(0.0003, 0.008 + 0.002 * i, n_obs)
            for i, ref in enumerate(assets)
        }
        return pd.DataFrame(data, index=index)

    monkeypatch.setattr(optimizer_data, "load_aligned_returns", fake_load)


def _stub_aum(
    monkeypatch: pytest.MonkeyPatch, aum: dict[uuid.UUID, float | None] | None = None
) -> None:
    async def fake_aum(
        session: Any, fund_ids: list[uuid.UUID]
    ) -> dict[uuid.UUID, float | None]:
        if aum is not None:
            return {fund_id: aum.get(fund_id) for fund_id in fund_ids}
        return {fund_id: 1e9 * (i + 1) for i, fund_id in enumerate(fund_ids)}

    monkeypatch.setattr(optimizer_data, "load_fund_aum", fake_aum)


async def test_optimize_min_cvar_no_views_happy_path(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _stub_returns(monkeypatch)
    payload = {
        "assets": [_fund_ref(i) for i in range(4)],
        "objective": "min_cvar",
    }
    async with _client() as client:
        response = await client.post("/builder/optimize", json=payload)
    assert response.status_code == 200, response.text
    body = response.json()
    weights = [w["weight"] for w in body["weights"]]
    assert abs(sum(weights) - 1.0) < 1e-6
    assert all(-1e-9 <= w <= 0.25 + 1e-6 for w in weights)  # default cap
    assert body["diagnostics"]["status"] == "optimal"
    assert body["diagnostics"]["n_obs"] == 500
    assert body["diagnostics"]["mu_posterior"] is None
    assert body["expected"]["return_ann_bl"] is None
    assert body["expected"]["vol_ann"] > 0
    assert body["expected"]["cvar_95_in_sample"] > 0


async def test_optimize_with_absolute_view_returns_bl_diagnostics(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _stub_returns(monkeypatch)
    _stub_aum(monkeypatch)
    payload = {
        "assets": [_fund_ref(i) for i in range(4)],
        "objective": "min_cvar",
        "constraints": {"cap": 0.5},
        "views": [
            {"type": "absolute", "asset": _fund_ref(0), "q": 0.12, "confidence": 0.5}
        ],
    }
    async with _client() as client:
        response = await client.post("/builder/optimize", json=payload)
    assert response.status_code == 200, response.text
    body = response.json()
    assert abs(sum(w["weight"] for w in body["weights"]) - 1.0) < 1e-6
    assert body["diagnostics"]["mu_equilibrium"] is not None
    assert body["diagnostics"]["mu_posterior"] is not None
    assert body["expected"]["return_ann_bl"] is not None
    # The bullish view must raise the posterior μ of the viewed asset.
    assert (
        body["diagnostics"]["mu_posterior"][0] > body["diagnostics"]["mu_equilibrium"][0]
    )


async def test_optimize_bl_utility_without_views(monkeypatch: pytest.MonkeyPatch) -> None:
    _stub_returns(monkeypatch)
    _stub_aum(monkeypatch)
    payload = {
        "assets": [_fund_ref(i) for i in range(4)],
        "objective": "bl_utility",
        "constraints": {"cap": None},
    }
    async with _client() as client:
        response = await client.post("/builder/optimize", json=payload)
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["diagnostics"]["mu_equilibrium"] is not None
    assert body["diagnostics"]["mu_posterior"] is None


async def test_insufficient_history_maps_to_422(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_load(session: Any, assets: Any, **kwargs: Any) -> pd.DataFrame:
        raise ValueError(
            "insufficient common history: 120 overlapping observations across the 2 assets"
        )

    monkeypatch.setattr(optimizer_data, "load_aligned_returns", fake_load)
    payload = {"assets": [_fund_ref(0), _fund_ref(1)], "constraints": {"cap": 0.6}}
    async with _client() as client:
        response = await client.post("/builder/optimize", json=payload)
    assert response.status_code == 422
    assert "insufficient common history" in response.json()["detail"]


async def test_unknown_asset_maps_to_422(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_load(session: Any, assets: Any, **kwargs: Any) -> pd.DataFrame:
        raise ValueError(f"unknown asset or no NAV history in window: fund:{_FUND_IDS[0]}")

    monkeypatch.setattr(optimizer_data, "load_aligned_returns", fake_load)
    payload = {"assets": [_fund_ref(0), _fund_ref(1)], "constraints": {"cap": 0.6}}
    async with _client() as client:
        response = await client.post("/builder/optimize", json=payload)
    assert response.status_code == 422
    assert "unknown asset" in response.json()["detail"]


async def test_views_with_equity_universe_maps_to_422(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _stub_returns(monkeypatch)
    payload = {
        "assets": [_fund_ref(0), _fund_ref(1), {"kind": "equity", "ticker": "AAPL"}],
        "constraints": {"cap": 0.5},
        "views": [
            {"type": "absolute", "asset": _fund_ref(0), "q": 0.10, "confidence": 0.5}
        ],
    }
    async with _client() as client:
        response = await client.post("/builder/optimize", json=payload)
    assert response.status_code == 422
    detail = response.json()["detail"]
    assert "equities" in detail and "equity:AAPL" in detail


async def test_views_with_missing_fund_aum_maps_to_422(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _stub_returns(monkeypatch)
    _stub_aum(monkeypatch, aum={_FUND_IDS[0]: 5e9, _FUND_IDS[1]: None})
    payload = {
        "assets": [_fund_ref(0), _fund_ref(1)],
        "constraints": {"cap": 0.6},
        "views": [
            {"type": "absolute", "asset": _fund_ref(0), "q": 0.10, "confidence": 0.5}
        ],
    }
    async with _client() as client:
        response = await client.post("/builder/optimize", json=payload)
    assert response.status_code == 422
    detail = response.json()["detail"]
    assert "AUM" in detail and str(_FUND_IDS[1]) in detail


async def test_rank_deficient_views_map_to_422(monkeypatch: pytest.MonkeyPatch) -> None:
    _stub_returns(monkeypatch)
    _stub_aum(monkeypatch)
    payload = {
        "assets": [_fund_ref(i) for i in range(3)],
        "constraints": {"cap": 0.5},
        "views": [
            {"type": "absolute", "asset": _fund_ref(0), "q": 0.10, "confidence": 0.5},
            {"type": "absolute", "asset": _fund_ref(0), "q": 0.12, "confidence": 0.5},
        ],
    }
    async with _client() as client:
        response = await client.post("/builder/optimize", json=payload)
    assert response.status_code == 422
    assert "linearmente dependentes" in response.json()["detail"]


async def test_view_on_asset_outside_universe_maps_to_422(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _stub_returns(monkeypatch)
    _stub_aum(monkeypatch)
    payload = {
        "assets": [_fund_ref(0), _fund_ref(1)],
        "constraints": {"cap": 0.6},
        "views": [
            {"type": "absolute", "asset": _fund_ref(4), "q": 0.10, "confidence": 0.5}
        ],
    }
    async with _client() as client:
        response = await client.post("/builder/optimize", json=payload)
    assert response.status_code == 422
    assert "not in the request universe" in response.json()["detail"]
