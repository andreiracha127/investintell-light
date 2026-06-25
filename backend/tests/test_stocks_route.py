"""Tests for GET /stocks/{ticker}/prices.

The DB read is stubbed at the route-module boundary. Historical EOD reads are
DB-only: no live network, no live DB.
"""

import datetime as dt
from collections.abc import AsyncGenerator
from types import SimpleNamespace
from typing import Any

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from app.api.routes import stocks
from app.core.db import get_session
from app.main import create_app


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
    return app


@pytest.fixture
async def stub_client(monkeypatch: pytest.MonkeyPatch) -> AsyncGenerator[AsyncClient, None]:
    """Client against an app whose service + DB read are no-op stubs."""

    async def fake_select(*args: Any, **kwargs: Any) -> list[SimpleNamespace]:
        return [_row(dt.date(2026, 6, 8)), _row(dt.date(2026, 6, 9))]

    monkeypatch.setattr(stocks, "_select_price_rows", fake_select)
    transport = ASGITransport(app=_app_with_overrides())
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


async def _client_with_price_rows(
    monkeypatch: pytest.MonkeyPatch, rows: list[SimpleNamespace]
) -> AsyncClient:
    async def fake_select(*args: Any, **kwargs: Any) -> list[SimpleNamespace]:
        return rows

    monkeypatch.setattr(stocks, "_select_price_rows", fake_select)
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


async def test_quote_returns_latest_two_raw_closes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fake_quote_rows(session, ticker):
        assert ticker == "AAPL"
        return [(dt.date(2026, 6, 11), 105.0), (dt.date(2026, 6, 10), 100.0)]

    async def fake_name(session, ticker):
        assert ticker == "AAPL"
        return "Apple Inc."

    monkeypatch.setattr(stocks, "_select_latest_quote_rows", fake_quote_rows)
    monkeypatch.setattr(stocks, "_select_instrument_name", fake_name)
    transport = ASGITransport(app=_app_with_overrides())
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        response = await ac.get("/stocks/aapl/quote")

    assert response.status_code == 200
    body = response.json()
    assert body == {
        "ticker": "AAPL",
        "name": "Apple Inc.",
        "last_close": 105.0,
        "prev_close": 100.0,
        "change": 5.0,
        "change_pct": 0.05,
        "as_of": "2026-06-11",
    }


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


async def test_no_local_rows_returns_404(monkeypatch: pytest.MonkeyPatch) -> None:
    async with await _client_with_price_rows(monkeypatch, []) as ac:
        response = await ac.get("/stocks/ZZZZZZ/prices")
    assert response.status_code == 404
    assert "No price data" in response.json()["detail"]


async def test_quote_no_local_rows_returns_404(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def empty(session, ticker):
        return []

    monkeypatch.setattr(stocks, "_select_latest_quote_rows", empty)
    transport = ASGITransport(app=_app_with_overrides())
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        response = await ac.get("/stocks/ZZZZZZ/quote")

    assert response.status_code == 404
    assert "No price data" in response.json()["detail"]


async def test_quote_single_row_returns_422(monkeypatch: pytest.MonkeyPatch) -> None:
    async def one_row(session, ticker):
        return [(dt.date(2026, 6, 11), 105.0)]

    monkeypatch.setattr(stocks, "_select_latest_quote_rows", one_row)
    transport = ASGITransport(app=_app_with_overrides())
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        response = await ac.get("/stocks/AAPL/quote")

    assert response.status_code == 422
    assert "one-day change" in response.json()["detail"]


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

    async def fake_select(*args: Any, **kwargs: Any) -> list[SimpleNamespace]:
        return [_row(dt.date(2026, 1, 1))] * (max_points + 1)

    monkeypatch.setattr(stocks, "_select_price_rows", fake_select)
    transport = ASGITransport(app=_app_with_overrides())
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        response = await ac.get("/stocks/AAPL/prices")
    assert response.status_code == 422
    assert "narrow" in response.json()["detail"].lower()
