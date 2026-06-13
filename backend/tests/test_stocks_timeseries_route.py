"""GET /stocks/{ticker}/timeseries — Highcharts OHLC arrays (DB stubbed)."""
import datetime as dt

from httpx import ASGITransport, AsyncClient

import app.api.routes.stocks as stocks_routes
from app.core.db import get_session
from app.core.tiingo_provider import get_tiingo_client
from app.main import create_app


def _client() -> AsyncClient:
    app = create_app()
    app.dependency_overrides[get_session] = lambda: None
    app.dependency_overrides[get_tiingo_client] = lambda: None
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


async def test_stock_timeseries_ohlc_arrays(monkeypatch) -> None:
    async def fake_ensure(session, client, symbols, start, end):
        return None

    async def fake_select(session, ticker, interval, start):
        assert ticker == "SPY" and interval == "daily"
        return [(dt.date(2026, 6, 11), 1.0, 2.0, 0.5, 1.8, 1000)]

    monkeypatch.setattr(stocks_routes, "_ensure_eod_or_http_error", fake_ensure)
    monkeypatch.setattr(stocks_routes, "_select_eod_ohlc", fake_select)
    async with _client() as client:
        resp = await client.get("/stocks/spy/timeseries?range=1Y")
    assert resp.status_code == 200
    body = resp.json()
    t = int(dt.datetime(2026, 6, 11, tzinfo=dt.UTC).timestamp() * 1000)
    assert body["interval"] == "daily"
    assert body["ohlc"] == [[t, 1.0, 2.0, 0.5, 1.8]]
    assert body["volume"] == [[t, 1000.0]]
