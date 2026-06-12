"""Tests de GET /stocks/{ticker}/history (selectors stubados, sem DB/Tiingo)."""

import datetime as dt

import pytest
from httpx import ASGITransport, AsyncClient

from app.core.db import get_session
from app.core.tiingo_provider import get_tiingo_client
from app.main import create_app

import app.api.routes.stocks as stocks_routes


def _client() -> AsyncClient:
    app = create_app()
    app.dependency_overrides[get_session] = lambda: None
    app.dependency_overrides[get_tiingo_client] = lambda: None
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


def _rows() -> list[tuple]:
    # (date, adj_open, adj_high, adj_low, adj_close, adj_volume)
    return [
        (dt.date(2026, 6, 10), 100.0, 105.0, 99.0, 104.0, 1_000_000),
        (dt.date(2026, 6, 11), 104.0, 106.0, 103.0, 105.5, 1_200_000),
    ]


@pytest.fixture(autouse=True)
def _stub(monkeypatch: pytest.MonkeyPatch):
    async def fake_ensure(session, client, symbols, start, end):
        assert symbols == ["TSLA"]

    async def fake_select(session, ticker, start, end):
        assert ticker == "TSLA"
        return _rows()

    monkeypatch.setattr(stocks_routes, "_ensure_eod_or_http_error", fake_ensure)
    monkeypatch.setattr(stocks_routes, "_select_adj_ohlcv_rows", fake_select)


@pytest.mark.anyio
async def test_history_contract_t_o_h_l_c_v() -> None:
    async with _client() as client:
        resp = await client.get("/stocks/tsla/history?bars=760")
    assert resp.status_code == 200
    body = resp.json()
    assert body["ticker"] == "TSLA" and body["count"] == 2
    bar = body["bars"][-1]
    # t = epoch ms UTC de 2026-06-11
    assert bar["t"] == int(dt.datetime(2026, 6, 11, tzinfo=dt.timezone.utc).timestamp() * 1000)
    assert (bar["o"], bar["h"], bar["l"], bar["c"], bar["v"]) == (104.0, 106.0, 103.0, 105.5, 1_200_000)


@pytest.mark.anyio
async def test_history_truncates_to_bars_param() -> None:
    async with _client() as client:
        resp = await client.get("/stocks/TSLA/history?bars=30")
    # 2 linhas stubadas < 30 → todas voltam; o recorte é dos N MAIS RECENTES
    assert resp.json()["count"] == 2


@pytest.mark.anyio
async def test_history_404_when_no_rows(monkeypatch: pytest.MonkeyPatch) -> None:
    async def ensure_any(session, client, symbols, start, end):
        return None

    async def empty(session, ticker, start, end):
        return []

    monkeypatch.setattr(stocks_routes, "_ensure_eod_or_http_error", ensure_any)
    monkeypatch.setattr(stocks_routes, "_select_adj_ohlcv_rows", empty)
    async with _client() as client:
        resp = await client.get("/stocks/ZZZZ/history")
    assert resp.status_code == 404


@pytest.mark.anyio
async def test_history_bars_validation() -> None:
    async with _client() as client:
        resp = await client.get("/stocks/TSLA/history?bars=2")
    assert resp.status_code == 422
