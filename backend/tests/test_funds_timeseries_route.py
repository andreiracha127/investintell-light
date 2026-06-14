"""GET /funds/{id}/timeseries — Highcharts NAV line arrays (DB stubbed)."""
import datetime as dt
import uuid

from httpx import ASGITransport, AsyncClient

import app.api.routes.funds as funds_routes
from app.core.db import get_session
from app.core.tiingo_provider import get_tiingo_client
from app.main import create_app

_FUND_ID = uuid.UUID("00000000-0000-0000-0000-000000000001")


def _client() -> AsyncClient:
    app = create_app()
    app.dependency_overrides[get_session] = lambda: None
    app.dependency_overrides[get_tiingo_client] = lambda: None
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


async def test_fund_timeseries_line_arrays(monkeypatch) -> None:
    async def fake_select(session, instrument_id, interval, start):
        assert str(instrument_id) == str(_FUND_ID) and interval == "weekly"
        return [(dt.date(2026, 6, 5), 306.2)]

    monkeypatch.setattr(funds_routes, "_select_nav_line", fake_select)
    async with _client() as client:
        resp = await client.get(f"/funds/{_FUND_ID}/timeseries?range=5Y")
    assert resp.status_code == 200
    body = resp.json()
    t = int(dt.datetime(2026, 6, 5, tzinfo=dt.UTC).timestamp() * 1000)
    assert body["interval"] == "weekly"
    assert body["series"] == [[t, 306.2]]
