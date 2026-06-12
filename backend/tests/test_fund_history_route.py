"""Tests de GET /funds/{instrument_id}/history (helpers stubados, sem DB/Tiingo)."""

import datetime as dt
import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from httpx import ASGITransport, AsyncClient

import app.api.routes.funds as funds_routes
from app.core.db import get_session
from app.core.tiingo_provider import get_tiingo_client
from app.main import create_app
from app.tiingo.exceptions import TiingoError

FUND_ID = uuid.uuid4()


def _client(session_factory=None) -> AsyncClient:
    app = create_app()
    app.dependency_overrides[get_session] = session_factory or (lambda: None)
    app.dependency_overrides[get_tiingo_client] = lambda: None
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


def _async_session_stub() -> AsyncMock:
    """Return a lightweight async session stub with a no-op rollback()."""
    stub = AsyncMock()
    stub.rollback = AsyncMock(return_value=None)
    return stub


def _etf() -> SimpleNamespace:
    return SimpleNamespace(instrument_id=FUND_ID, ticker="SPY", fund_type="etf")


def _mutual() -> SimpleNamespace:
    return SimpleNamespace(instrument_id=FUND_ID, ticker="VFIAX", fund_type="mutual_fund")


OHLCV_ROWS = [
    (dt.date(2026, 6, 10), 100.0, 105.0, 99.0, 104.0, 1_000_000),
    (dt.date(2026, 6, 11), 104.0, 106.0, 103.0, 105.5, 1_200_000),
]
NAV_ROWS = [(dt.date(2026, 6, 10), 412.31), (dt.date(2026, 6, 11), 414.02)]


@pytest.fixture(autouse=True)
def _stub(monkeypatch: pytest.MonkeyPatch):
    async def get_fund(session, instrument_id):
        return _etf()

    async def ensure(session, client, symbols, start, end):
        return None

    async def adj(session, ticker, start, end):
        assert ticker == "SPY"
        return OHLCV_ROWS

    async def nav(session, instrument_id, start, end):
        return NAV_ROWS

    monkeypatch.setattr(funds_routes, "_get_fund", get_fund)
    monkeypatch.setattr(funds_routes, "_ensure_eod_or_http_error", ensure)
    monkeypatch.setattr(funds_routes, "_select_adj_ohlcv_rows", adj)
    monkeypatch.setattr(funds_routes, "_select_nav_rows", nav)


@pytest.mark.anyio
async def test_etf_uses_ohlcv_path() -> None:
    async with _client() as client:
        resp = await client.get(f"/funds/{FUND_ID}/history?bars=100")
    assert resp.status_code == 200
    body = resp.json()
    assert body["mode"] == "ohlcv" and body["ticker"] == "SPY" and body["count"] == 2
    bar = body["bars"][-1]
    assert bar["t"] == int(dt.datetime(2026, 6, 11, tzinfo=dt.UTC).timestamp() * 1000)
    assert (bar["o"], bar["h"], bar["l"], bar["c"], bar["v"]) == (
        104.0, 106.0, 103.0, 105.5, 1_200_000
    )


@pytest.mark.anyio
async def test_mutual_fund_uses_nav_path(monkeypatch: pytest.MonkeyPatch) -> None:
    async def get_fund(session, instrument_id):
        return _mutual()

    monkeypatch.setattr(funds_routes, "_get_fund", get_fund)
    async with _client() as client:
        resp = await client.get(f"/funds/{FUND_ID}/history")
    assert resp.status_code == 200
    body = resp.json()
    assert body["mode"] == "nav" and body["count"] == 2
    bar = body["bars"][-1]
    assert bar["o"] == bar["h"] == bar["l"] == bar["c"] == 414.02
    assert bar["v"] == 0


@pytest.mark.anyio
async def test_etf_degrades_to_nav_when_tiingo_fails(monkeypatch: pytest.MonkeyPatch) -> None:
    async def ensure(session, client, symbols, start, end):
        raise TiingoError("down")

    session_stub = _async_session_stub()
    monkeypatch.setattr(funds_routes, "_ensure_eod_or_http_error", ensure)
    async with _client(session_factory=lambda: session_stub) as client:
        resp = await client.get(f"/funds/{FUND_ID}/history")
    assert resp.status_code == 200
    assert resp.json()["mode"] == "nav"
    session_stub.rollback.assert_awaited_once()


@pytest.mark.anyio
async def test_404_unknown_fund(monkeypatch: pytest.MonkeyPatch) -> None:
    async def none(session, instrument_id):
        return None

    monkeypatch.setattr(funds_routes, "_get_fund", none)
    async with _client() as client:
        resp = await client.get(f"/funds/{FUND_ID}/history")
    assert resp.status_code == 404


@pytest.mark.anyio
async def test_404_when_no_series_at_all(monkeypatch: pytest.MonkeyPatch) -> None:
    async def get_fund(session, instrument_id):
        return _mutual()

    async def empty(session, instrument_id, start, end):
        return []

    monkeypatch.setattr(funds_routes, "_get_fund", get_fund)
    monkeypatch.setattr(funds_routes, "_select_nav_rows", empty)
    async with _client() as client:
        resp = await client.get(f"/funds/{FUND_ID}/history")
    assert resp.status_code == 404


@pytest.mark.anyio
async def test_bars_validation() -> None:
    async with _client() as client:
        resp = await client.get(f"/funds/{FUND_ID}/history?bars=2")
    assert resp.status_code == 422
