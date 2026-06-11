"""Tests for GET /stocks/{ticker}/analysis.

The ingestion service and DB read helpers are stubbed at the route-module
boundary; the Tiingo client and DB session dependencies are overridden.
No live network, no live DB.
"""

import datetime as dt
from collections.abc import AsyncGenerator
from typing import Any

import numpy as np
import pandas as pd
import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from app.api import _shared as api_shared
from app.api.routes import stocks
from app.core.db import get_session
from app.core.tiingo_provider import get_tiingo_client
from app.ingestion.service import EnsureReport
from app.main import create_app
from app.tiingo.exceptions import TiingoNotFoundError

N_DAYS = 420

OhlcvRow = tuple[dt.date, float, float, float, float, int, float]


def _synthetic_rows(seed: int) -> list[OhlcvRow]:
    """~420 business days of OHLCV ending near today, deterministic walk."""
    dates = pd.bdate_range(end=dt.date.today(), periods=N_DAYS)
    rng = np.random.default_rng(seed)
    closes = 100.0 * np.cumprod(1 + rng.normal(0.0004, 0.01, N_DAYS))
    return [
        (ts.date(), c * 0.99, c * 1.02, c * 0.98, c, 1_000, c)
        for ts, c in zip(dates, closes, strict=True)
    ]


ASSET_ROWS = _synthetic_rows(seed=1)
BENCH_ROWS = _synthetic_rows(seed=2)


def _app_with_overrides() -> FastAPI:
    app = create_app()
    app.dependency_overrides[get_session] = lambda: None
    app.dependency_overrides[get_tiingo_client] = lambda: object()
    return app


def _install_stubs(
    monkeypatch: pytest.MonkeyPatch,
    asset_rows: list[OhlcvRow] | None = None,
) -> None:
    rows = ASSET_ROWS if asset_rows is None else asset_rows

    async def fake_ensure(*args: Any, **kwargs: Any) -> EnsureReport:
        return EnsureReport()

    async def fake_bounds(
        session: Any, ticker: str
    ) -> tuple[dt.date | None, dt.date | None]:
        if not rows:
            return None, None
        return rows[0][0], rows[-1][0]

    async def fake_ohlcv(
        session: Any, ticker: str, start: dt.date, end: dt.date
    ) -> list[OhlcvRow]:
        return [r for r in rows if start <= r[0] <= end]

    async def fake_adj_close(
        session: Any, ticker: str, start: dt.date, end: dt.date
    ) -> list[tuple[dt.date, float]]:
        return [(r[0], r[6]) for r in BENCH_ROWS if start <= r[0] <= end]

    async def fake_name(session: Any, ticker: str) -> str | None:
        return "Apple Inc"

    # ensure_eod_data is called from app.api._shared — patch the canonical location.
    monkeypatch.setattr(api_shared, "ensure_eod_data", fake_ensure)
    monkeypatch.setattr(stocks, "_select_date_bounds", fake_bounds)
    monkeypatch.setattr(stocks, "_select_ohlcv_rows", fake_ohlcv)
    monkeypatch.setattr(stocks, "_select_adj_close_rows", fake_adj_close)
    monkeypatch.setattr(stocks, "_select_instrument_name", fake_name)


@pytest.fixture
async def stub_client(monkeypatch: pytest.MonkeyPatch) -> AsyncGenerator[AsyncClient, None]:
    _install_stubs(monkeypatch)
    transport = ASGITransport(app=_app_with_overrides())
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------


async def test_happy_path_shape(stub_client: AsyncClient) -> None:
    response = await stub_client.get("/stocks/aapl/analysis", params={"range": "1Y"})
    assert response.status_code == 200
    body = response.json()
    assert set(body) == {
        "params",
        "header",
        "candles",
        "cumulative_returns",
        "rolling_volatility",
        "rolling_beta",
        "rolling_correlation",
        "histogram",
        "stats",
    }
    assert body["params"]["range"] == "1Y"
    assert body["params"]["benchmark"] == "SPY"
    assert body["params"]["window"] == 63
    assert body["params"]["end_date"] == ASSET_ROWS[-1][0].isoformat()

    assert body["header"]["ticker"] == "AAPL"
    assert body["header"]["name"] == "Apple Inc"
    assert body["header"]["last_close"] > 0
    assert body["header"]["as_of"] == ASSET_ROWS[-1][0].isoformat()

    assert body["candles"][0].keys() == {"date", "open", "high", "low", "close", "volume"}
    assert set(body["cumulative_returns"]) == {"asset", "benchmark"}
    # Series points serialize as [iso_date, value] pairs.
    first_point = body["rolling_volatility"][0]
    assert len(first_point) == 2
    assert dt.date.fromisoformat(first_point[0])
    assert isinstance(first_point[1], float)

    assert set(body["histogram"]) == {"bin_edges", "counts", "counts_normalized"}
    assert len(body["histogram"]["counts"]) == 20
    assert body["stats"]["var_99"] >= body["stats"]["var_95"]


async def test_benchmark_and_window_are_echoed(stub_client: AsyncClient) -> None:
    response = await stub_client.get(
        "/stocks/AAPL/analysis", params={"benchmark": "msft", "window": 30}
    )
    assert response.status_code == 200
    body = response.json()
    assert body["params"]["benchmark"] == "MSFT"
    assert body["params"]["window"] == 30


# ---------------------------------------------------------------------------
# Error paths
# ---------------------------------------------------------------------------


async def test_unknown_ticker_returns_404(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_ensure(*args: Any, **kwargs: Any) -> EnsureReport:
        raise TiingoNotFoundError("nope")

    monkeypatch.setattr(api_shared, "ensure_eod_data", fake_ensure)
    transport = ASGITransport(app=_app_with_overrides())
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        response = await ac.get("/stocks/ZZZZZZ/analysis")
    assert response.status_code == 404
    assert "ZZZZZZ" in response.json()["detail"]


async def test_no_price_rows_returns_404(monkeypatch: pytest.MonkeyPatch) -> None:
    _install_stubs(monkeypatch, asset_rows=[])
    transport = ASGITransport(app=_app_with_overrides())
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        response = await ac.get("/stocks/AAPL/analysis")
    assert response.status_code == 404
    assert "No price data" in response.json()["detail"]


async def test_insufficient_history_returns_422(monkeypatch: pytest.MonkeyPatch) -> None:
    # Only 5 rows of history: too few in-range returns for the stats block.
    _install_stubs(monkeypatch, asset_rows=ASSET_ROWS[-5:])
    transport = ASGITransport(app=_app_with_overrides())
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        response = await ac.get("/stocks/AAPL/analysis", params={"range": "1M"})
    assert response.status_code == 422
    assert "history" in response.json()["detail"].lower()


@pytest.mark.parametrize("window", [9, 253])
async def test_window_out_of_bounds_returns_422(stub_client: AsyncClient, window: int) -> None:
    response = await stub_client.get("/stocks/AAPL/analysis", params={"window": window})
    assert response.status_code == 422


async def test_invalid_range_returns_422(stub_client: AsyncClient) -> None:
    response = await stub_client.get("/stocks/AAPL/analysis", params={"range": "2Y"})
    assert response.status_code == 422
