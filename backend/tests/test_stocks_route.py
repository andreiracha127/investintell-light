"""Tests for GET /stocks/{ticker}/prices.

The ingestion service and the DB read are stubbed at the route-module
boundary; the Tiingo client and DB session dependencies are overridden.
No live network, no live DB.
"""

import datetime as dt
from collections.abc import AsyncGenerator
from types import SimpleNamespace
from typing import Any

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from app.api import _shared as api_shared
from app.api.routes import stocks
from app.core.db import get_session
from app.core.tiingo_provider import get_tiingo_client
from app.ingestion.service import ColdTickerCapExceededError, EnsureReport
from app.main import create_app
from app.tiingo.exceptions import (
    TiingoAuthError,
    TiingoNotFoundError,
    TiingoRateLimitError,
    TiingoServerError,
)


def _row(day: dt.date) -> SimpleNamespace:
    return SimpleNamespace(
        date=day,
        open=1.0,
        high=2.0,
        low=0.5,
        close=1.5,
        volume=100,
        adj_close=1.5,
        div_cash=0.0,
        split_factor=1.0,
    )


def _app_with_overrides() -> FastAPI:
    app = create_app()
    app.dependency_overrides[get_session] = lambda: None
    app.dependency_overrides[get_tiingo_client] = lambda: object()
    return app


@pytest.fixture
async def stub_client(monkeypatch: pytest.MonkeyPatch) -> AsyncGenerator[AsyncClient, None]:
    """Client against an app whose service + DB read are no-op stubs."""

    async def fake_ensure(*args: Any, **kwargs: Any) -> EnsureReport:
        return EnsureReport()

    async def fake_select(*args: Any, **kwargs: Any) -> list[SimpleNamespace]:
        return [_row(dt.date(2026, 6, 8)), _row(dt.date(2026, 6, 9))]

    # ensure_eod_data is called from app.api._shared (the canonical location);
    # patch it there so both the stocks and portfolio routes see the stub.
    monkeypatch.setattr(api_shared, "ensure_eod_data", fake_ensure)
    monkeypatch.setattr(stocks, "_select_price_rows", fake_select)
    transport = ASGITransport(app=_app_with_overrides())
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


async def _client_with_failing_service(
    monkeypatch: pytest.MonkeyPatch, exc: Exception
) -> AsyncClient:
    async def fake_ensure(*args: Any, **kwargs: Any) -> EnsureReport:
        raise exc

    monkeypatch.setattr(api_shared, "ensure_eod_data", fake_ensure)
    transport = ASGITransport(app=_app_with_overrides())
    return AsyncClient(transport=transport, base_url="http://test")


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------


async def test_happy_path_shape(stub_client: AsyncClient) -> None:
    response = await stub_client.get(
        "/stocks/aapl/prices",
        params={"start_date": "2026-06-01", "end_date": "2026-06-09"},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["ticker"] == "AAPL"
    assert body["start_date"] == "2026-06-01"
    assert body["end_date"] == "2026-06-09"
    assert body["count"] == 2
    assert len(body["prices"]) == 2
    assert body["prices"][0] == {
        "date": "2026-06-08",
        "open": 1.0,
        "high": 2.0,
        "low": 0.5,
        "close": 1.5,
        "volume": 100,
        "adj_close": 1.5,
        "div_cash": 0.0,
        "split_factor": 1.0,
    }
    # Lean payload: full adjusted OHLC and adj_volume are NOT exposed.
    assert "adj_open" not in body["prices"][0]
    assert "adj_volume" not in body["prices"][0]


async def test_default_window_is_365_days(stub_client: AsyncClient) -> None:
    response = await stub_client.get("/stocks/AAPL/prices")
    assert response.status_code == 200
    body = response.json()
    end = dt.date.fromisoformat(body["end_date"])
    start = dt.date.fromisoformat(body["start_date"])
    assert end == dt.date.today()
    assert end - start == dt.timedelta(days=365)


# ---------------------------------------------------------------------------
# Error mapping
# ---------------------------------------------------------------------------


async def test_unknown_ticker_returns_404(monkeypatch: pytest.MonkeyPatch) -> None:
    async with await _client_with_failing_service(
        monkeypatch, TiingoNotFoundError("nope")
    ) as ac:
        response = await ac.get("/stocks/ZZZZZZ/prices")
    assert response.status_code == 404
    assert "ZZZZZZ" in response.json()["detail"]


async def test_rate_limited_returns_503(monkeypatch: pytest.MonkeyPatch) -> None:
    async with await _client_with_failing_service(
        monkeypatch, TiingoRateLimitError("hourly cap")
    ) as ac:
        response = await ac.get("/stocks/AAPL/prices")
    assert response.status_code == 503


async def test_auth_error_returns_502_without_detail_leak(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async with await _client_with_failing_service(
        monkeypatch, TiingoAuthError("HTTP 401: bad token sk-secret")
    ) as ac:
        response = await ac.get("/stocks/AAPL/prices")
    assert response.status_code == 502
    assert "sk-secret" not in response.json()["detail"]


async def test_server_error_returns_502(monkeypatch: pytest.MonkeyPatch) -> None:
    async with await _client_with_failing_service(
        monkeypatch, TiingoServerError("HTTP 500 from Tiingo")
    ) as ac:
        response = await ac.get("/stocks/AAPL/prices")
    assert response.status_code == 502


async def test_cold_cap_exceeded_returns_422(monkeypatch: pytest.MonkeyPatch) -> None:
    async with await _client_with_failing_service(
        monkeypatch, ColdTickerCapExceededError("too many cold tickers")
    ) as ac:
        response = await ac.get("/stocks/AAPL/prices")
    assert response.status_code == 422
    assert "too many cold tickers" in response.json()["detail"]


async def test_inverted_dates_return_422(stub_client: AsyncClient) -> None:
    response = await stub_client.get(
        "/stocks/AAPL/prices",
        params={"start_date": "2026-06-09", "end_date": "2026-06-01"},
    )
    assert response.status_code == 422


async def test_window_exceeding_max_points_returns_422(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.core.config import get_settings

    max_points = get_settings().price_series_max_points

    async def fake_ensure(*args: Any, **kwargs: Any) -> EnsureReport:
        return EnsureReport()

    async def fake_select(*args: Any, **kwargs: Any) -> list[SimpleNamespace]:
        return [_row(dt.date(2026, 1, 1))] * (max_points + 1)

    monkeypatch.setattr(api_shared, "ensure_eod_data", fake_ensure)
    monkeypatch.setattr(stocks, "_select_price_rows", fake_select)
    transport = ASGITransport(app=_app_with_overrides())
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        response = await ac.get("/stocks/AAPL/prices")
    assert response.status_code == 422
    assert "narrow" in response.json()["detail"].lower()
