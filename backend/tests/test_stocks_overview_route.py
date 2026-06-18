"""Tests de GET /stocks/overview (service stubado, sem DB/Tiingo)."""

import datetime as dt

import pytest
from httpx import ASGITransport, AsyncClient

from app.core.db import get_session
from app.core.tiingo_provider import get_tiingo_client
from app.main import create_app
from app.schemas.market import IndexCard, LeaderRow, MarketBreadth, SectorPerf
from app.services import market_overview as mo
from app.tiingo.exceptions import TiingoError


def _client() -> AsyncClient:
    app = create_app()
    app.dependency_overrides[get_session] = lambda: None
    app.dependency_overrides[get_tiingo_client] = lambda: None
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


def _leader(ticker: str = "NVDA") -> LeaderRow:
    return LeaderRow(ticker=ticker, name="NVIDIA", sector="Information Technology",
                     last=171.4, change=4.2, change_pct=0.0251, volume=160_000_000,
                     high_52w=190.0, low_52w=90.0)


def _patch_happy(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_rows(session):
        return ["sentinel"]

    async def fake_indices(session):
        return [IndexCard(ticker="SPY", name="S&P 500", last=672.3,
                          change_pct=0.004, spark=[670.0, 672.3])]

    def fake_rank(rows):
        assert rows == ["sentinel"]
        return mo.RankedOverview(
            as_of=dt.date(2026, 6, 11), most_active=[_leader()], gainers=[_leader()],
            losers=[], highs_52w=[], lows_52w=[],
            sectors=[SectorPerf(sector="Energy", change_pct_median=0.01, n=12)],
            breadth=MarketBreadth(
                tracked=1, advancing=1, declining=0, unchanged=0,
                advance_decline_ratio=1.0, new_highs_52w=0, new_lows_52w=0,
                up_volume_share=1.0,
            ),
        )

    monkeypatch.setattr(mo, "fetch_overview_rows", fake_rows)
    monkeypatch.setattr(mo, "fetch_index_rows", fake_indices)
    monkeypatch.setattr(mo, "rank_overview", fake_rank)


@pytest.mark.anyio
async def test_overview_assembles_payload(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_happy(monkeypatch)

    async def fake_ensure(session, client, symbols, start, end):
        assert set(symbols) == set(mo.INDEX_TICKERS)

    import app.api.routes.stocks as stocks_routes
    monkeypatch.setattr(stocks_routes, "_ensure_eod_or_http_error", fake_ensure)

    async with _client() as client:
        resp = await client.get("/stocks/overview")
    assert resp.status_code == 200
    body = resp.json()
    assert body["as_of"] == "2026-06-11"
    assert body["gainers"][0]["ticker"] == "NVDA"
    assert body["indices"][0]["ticker"] == "SPY"
    assert body["sectors"][0]["sector"] == "Energy"
    assert body["universe_size"] == 1
    assert body["breadth"]["advancing"] == 1 and body["breadth"]["tracked"] == 1


@pytest.mark.anyio
async def test_overview_degrades_indices_when_tiingo_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Índices são painel secundário: falha da Tiingo degrada para [], não 5xx."""
    _patch_happy(monkeypatch)

    async def fake_ensure(session, client, symbols, start, end):
        raise TiingoError("down")

    import app.api.routes.stocks as stocks_routes
    monkeypatch.setattr(stocks_routes, "_ensure_eod_or_http_error", fake_ensure)

    async with _client() as client:
        resp = await client.get("/stocks/overview")
    assert resp.status_code == 200
    assert resp.json()["indices"] == []
    assert resp.json()["gainers"][0]["ticker"] == "NVDA"
