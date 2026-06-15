"""Tests for GET /macro/fiscal (treasury fiscal series, DB-first).

treasury_data is materialized by the treasury_ingestion worker; the Light only
reads. Service stubbed at its canonical module — no live DB.
"""

import datetime as dt

import pytest
from httpx import ASGITransport, AsyncClient

from app.core.datalake import get_datalake_session
from app.main import create_app
from app.services import treasury_fiscal as tf


def _client() -> AsyncClient:
    app = create_app()
    app.dependency_overrides[get_datalake_session] = lambda: None
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


def _fiscal(prefix: str = "RATE_") -> tf.FiscalData:
    return tf.FiscalData(
        prefix=prefix,
        series=[
            tf.FiscalSeries(
                series_id="RATE_TREASURY_BILLS",
                points=[
                    tf.FiscalPoint(dt.date(2026, 5, 1), 5.05, None),
                    tf.FiscalPoint(dt.date(2026, 6, 1), 5.10, None),
                ],
            ),
        ],
    )


def _fiscal_auctions() -> tf.FiscalData:
    meta = {"security_type": "Bond", "security_term": "30-Year", "bid_to_cover": 2.4}
    return tf.FiscalData(
        prefix="AUCTION_",
        series=[
            tf.FiscalSeries(
                series_id="AUCTION_BOND_30_YEAR",
                points=[tf.FiscalPoint(dt.date(2026, 6, 11), 5.02, meta)],
            ),
        ],
    )


@pytest.mark.anyio
async def test_fiscal_returns_series_for_category(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict = {}

    async def fake_fetch(datalake, *, prefix, lookback_days):
        captured["prefix"] = prefix
        captured["lookback_days"] = lookback_days
        return _fiscal(prefix)

    monkeypatch.setattr(tf, "fetch_treasury_series", fake_fetch)
    async with _client() as client:
        resp = await client.get("/macro/fiscal", params={"category": "rates"})
    assert resp.status_code == 200
    assert captured["prefix"] == "RATE_"
    body = resp.json()
    assert body["category"] == "rates"
    assert body["prefix"] == "RATE_"
    s = body["series"][0]
    assert s["series_id"] == "RATE_TREASURY_BILLS"
    assert s["points"][0]["obs_date"] == "2026-05-01"
    assert s["points"][1]["value"] == 5.10
    assert s["points"][0]["metadata"] is None


@pytest.mark.anyio
async def test_fiscal_passes_auction_metadata(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_fetch(datalake, *, prefix, lookback_days):
        return _fiscal_auctions()

    monkeypatch.setattr(tf, "fetch_treasury_series", fake_fetch)
    async with _client() as client:
        resp = await client.get("/macro/fiscal", params={"category": "auctions"})
    assert resp.status_code == 200
    pt = resp.json()["series"][0]["points"][0]
    assert pt["metadata"]["security_type"] == "Bond"
    assert pt["metadata"]["bid_to_cover"] == 2.4


@pytest.mark.anyio
async def test_fiscal_default_category_is_rates(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict = {}

    async def fake_fetch(datalake, *, prefix, lookback_days):
        captured["prefix"] = prefix
        return _fiscal(prefix)

    monkeypatch.setattr(tf, "fetch_treasury_series", fake_fetch)
    async with _client() as client:
        resp = await client.get("/macro/fiscal")
    assert resp.status_code == 200
    assert captured["prefix"] == "RATE_"


@pytest.mark.anyio
async def test_fiscal_invalid_category_422() -> None:
    async with _client() as client:
        resp = await client.get("/macro/fiscal", params={"category": "bogus"})
    assert resp.status_code == 422


@pytest.mark.anyio
async def test_fiscal_404_when_empty(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_fetch(datalake, *, prefix, lookback_days):
        return tf.FiscalData(prefix=prefix, series=[])

    monkeypatch.setattr(tf, "fetch_treasury_series", fake_fetch)
    async with _client() as client:
        resp = await client.get("/macro/fiscal", params={"category": "debt"})
    assert resp.status_code == 404
    assert "treasury_ingestion" in resp.json()["detail"]
