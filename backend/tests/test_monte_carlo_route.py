"""Tests for POST /monte-carlo/projection.

DB read helpers are stubbed at the SERVICE-module boundary (the canonical
pattern from test_statistics_routes.py). Historical EOD data is DB-only:
no live network, no live DB.
"""

import datetime as dt
from collections.abc import AsyncGenerator
from typing import Any

import numpy as np
import pandas as pd
import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from app.core.db import get_session
from app.main import create_app
from app.services import monte_carlo as mc_service

N_DAYS = 800
AdjCloseRow = tuple[dt.date, float]


def _synthetic_rows(seed: int, n_days: int = N_DAYS) -> list[AdjCloseRow]:
    dates = pd.bdate_range(end=dt.date.today(), periods=n_days)
    rng = np.random.default_rng(seed)
    closes = 100.0 * np.cumprod(1 + rng.normal(0.0004, 0.01, n_days))
    return [(ts.date(), float(c)) for ts, c in zip(dates, closes, strict=True)]


ROWS_BY_TICKER: dict[str, list[AdjCloseRow]] = {"AAPL": _synthetic_rows(seed=1)}


def _app_with_overrides() -> FastAPI:
    app = create_app()
    app.dependency_overrides[get_session] = lambda: None
    return app


def _install_stubs(
    monkeypatch: pytest.MonkeyPatch,
    rows_by_ticker: dict[str, list[AdjCloseRow]] | None = None,
) -> None:
    rows_map = ROWS_BY_TICKER if rows_by_ticker is None else rows_by_ticker

    async def fake_bounds(
        session: Any, ticker: str
    ) -> tuple[dt.date | None, dt.date | None]:
        rows = rows_map.get(ticker, [])
        if not rows:
            return None, None
        return rows[0][0], rows[-1][0]

    async def fake_adj_close(
        session: Any, ticker: str, start: dt.date, end: dt.date
    ) -> list[AdjCloseRow]:
        return [r for r in rows_map.get(ticker, []) if start <= r[0] <= end]

    # Read helpers are looked up as SERVICE-module globals (underscore aliases
    # to app.services._series).
    monkeypatch.setattr(mc_service, "_select_date_bounds", fake_bounds)
    monkeypatch.setattr(mc_service, "_select_adj_close_rows", fake_adj_close)


@pytest.fixture
async def stub_client(
    monkeypatch: pytest.MonkeyPatch,
) -> AsyncGenerator[AsyncClient, None]:
    _install_stubs(monkeypatch)
    transport = ASGITransport(app=_app_with_overrides())
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


async def test_projection_happy_path_shape(stub_client: AsyncClient) -> None:
    response = await stub_client.post(
        "/monte-carlo/projection",
        json={
            "ticker": "aapl",
            "statistic": "max_drawdown",
            "n_simulations": 2000,
            "seed": 7,
        },
    )
    assert response.status_code == 200
    body = response.json()
    assert set(body) == {
        "params", "percentiles", "mean", "median", "std",
        "historical_value", "historical_horizon_days",
        "historical_percentile_rank", "confidence_bars",
        "degraded", "degraded_reason",
    }
    assert body["params"]["ticker"] == "AAPL"
    assert body["params"]["statistic"] == "max_drawdown"
    assert body["params"]["seed"] == 7
    assert set(body["percentiles"].keys()) == {
        "1st", "5th", "10th", "25th", "50th", "75th", "90th", "95th", "99th"
    }
    assert body["confidence_bars"][0]["horizon"] == "1Y"
    assert body["degraded"] is False


async def test_projection_is_deterministic_under_seed(stub_client: AsyncClient) -> None:
    payload = {"ticker": "AAPL", "statistic": "return", "n_simulations": 1500, "seed": 5}
    a = (await stub_client.post("/monte-carlo/projection", json=payload)).json()
    b = (await stub_client.post("/monte-carlo/projection", json=payload)).json()
    assert a["percentiles"] == b["percentiles"]
    assert a["median"] == b["median"]


async def test_unknown_ticker_404(monkeypatch: pytest.MonkeyPatch) -> None:
    _install_stubs(monkeypatch, rows_by_ticker={})
    transport = ASGITransport(app=_app_with_overrides())
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        response = await ac.post("/monte-carlo/projection", json={"ticker": "ZZZZ"})
    assert response.status_code == 404


async def test_insufficient_history_422(monkeypatch: pytest.MonkeyPatch) -> None:
    # Only 30 business days: below the 42-return analytics floor -> 422.
    _install_stubs(
        monkeypatch, rows_by_ticker={"AAPL": _synthetic_rows(seed=1, n_days=30)}
    )
    transport = ASGITransport(app=_app_with_overrides())
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        response = await ac.post(
            "/monte-carlo/projection", json={"ticker": "AAPL", "range": "MAX"}
        )
    assert response.status_code == 422


async def test_bad_n_simulations_422(stub_client: AsyncClient) -> None:
    response = await stub_client.post(
        "/monte-carlo/projection", json={"ticker": "AAPL", "n_simulations": 1}
    )
    assert response.status_code == 422  # Pydantic bound violation
