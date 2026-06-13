"""Tests de GET /search/symbols (readers stubados, sem DB)."""

import pytest
from httpx import ASGITransport, AsyncClient

import app.api.routes.search as search_routes
from app.core.db import get_session
from app.main import create_app
from app.services.symbol_search import SymbolHit


def _client() -> AsyncClient:
    app = create_app()
    app.dependency_overrides[get_session] = lambda: None
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


@pytest.fixture(autouse=True)
def _stub(monkeypatch: pytest.MonkeyPatch):
    async def stocks(session, q):
        return [SymbolHit(symbol="SPYX", name="SPYX Inc", kind="stock", instrument_id=None)]

    async def funds(session, q):
        return [SymbolHit(symbol="SPY", name="SPDR S&P 500", kind="etf", instrument_id=None)]

    monkeypatch.setattr(search_routes, "fetch_stock_hits", stocks)
    monkeypatch.setattr(search_routes, "fetch_fund_hits", funds)


@pytest.mark.anyio
async def test_search_merges_and_ranks() -> None:
    async with _client() as client:
        resp = await client.get("/search/symbols?q=SPY")
    assert resp.status_code == 200
    body = resp.json()
    assert [r["symbol"] for r in body] == ["SPY", "SPYX"]  # exato primeiro
    assert body[0]["kind"] == "etf"


@pytest.mark.anyio
async def test_search_requires_q() -> None:
    async with _client() as client:
        assert (await client.get("/search/symbols")).status_code == 422
        assert (await client.get("/search/symbols?q=")).status_code == 422


@pytest.mark.anyio
async def test_search_limit_le_25() -> None:
    async with _client() as client:
        assert (await client.get("/search/symbols?q=A&limit=26")).status_code == 422
