"""Tests for GET /macro/regional and GET /macro/global-indicators.

The scorecards are materialized by the macro_ingestion worker into
macro_regional_snapshots; the Light only reads. Service stubbed at its canonical
module — no live DB.
"""

import datetime as dt

import pytest
from httpx import ASGITransport, AsyncClient

from app.core.datalake import get_datalake_session
from app.main import create_app
from app.services import macro_scorecards as ms


def _client() -> AsyncClient:
    app = create_app()
    app.dependency_overrides[get_datalake_session] = lambda: None
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


def _scorecards() -> ms.MacroScorecards:
    return ms.MacroScorecards(
        as_of_date=dt.date(2026, 6, 14),
        regions={
            "US": ms.RegionScorecard(
                region="US",
                composite_score=47.72,
                coverage=0.85,
                dimensions={
                    "growth": ms.DimensionScore(
                        score=57.93, n_indicators=4,
                        indicators={"PAYEMS": 100.0},
                    ),
                },
                data_freshness={
                    "CPIAUCSL": ms.DataFreshness(
                        last_date=dt.date(2026, 5, 31), days_stale=14,
                        weight=1.0, status="fresh",
                    ),
                },
            ),
        },
        global_indicators=ms.GlobalIndicators(
            geopolitical_risk_score=81.51,
            energy_stress=55.59,
            commodity_stress=100.0,
            usd_strength=54.36,
        ),
    )


@pytest.mark.anyio
async def test_regional_returns_scorecards(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_fetch(datalake):
        return _scorecards()

    monkeypatch.setattr(ms, "fetch_macro_scorecards", fake_fetch)
    async with _client() as client:
        resp = await client.get("/macro/regional")
    assert resp.status_code == 200
    body = resp.json()
    assert body["as_of_date"] == "2026-06-14"
    us = body["regions"]["US"]
    assert us["composite_score"] == 47.72
    assert us["coverage"] == 0.85
    assert us["dimensions"]["growth"]["score"] == 57.93
    assert us["dimensions"]["growth"]["indicators"]["PAYEMS"] == 100.0
    fr = us["data_freshness"]["CPIAUCSL"]
    assert fr["last_date"] == "2026-05-31"
    assert fr["status"] == "fresh"


@pytest.mark.anyio
async def test_global_indicators_returns_scores(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_fetch(datalake):
        return _scorecards()

    monkeypatch.setattr(ms, "fetch_macro_scorecards", fake_fetch)
    async with _client() as client:
        resp = await client.get("/macro/global-indicators")
    assert resp.status_code == 200
    body = resp.json()
    assert body["as_of_date"] == "2026-06-14"
    assert body["geopolitical_risk_score"] == 81.51
    assert body["energy_stress"] == 55.59
    assert body["commodity_stress"] == 100.0
    assert body["usd_strength"] == 54.36


@pytest.mark.anyio
async def test_regional_404_when_not_materialized(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_fetch(datalake):
        return None

    monkeypatch.setattr(ms, "fetch_macro_scorecards", fake_fetch)
    async with _client() as client:
        resp = await client.get("/macro/regional")
    assert resp.status_code == 404
    assert "macro_ingestion" in resp.json()["detail"]


@pytest.mark.anyio
async def test_global_indicators_404_when_not_materialized(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fake_fetch(datalake):
        return None

    monkeypatch.setattr(ms, "fetch_macro_scorecards", fake_fetch)
    async with _client() as client:
        resp = await client.get("/macro/global-indicators")
    assert resp.status_code == 404
    assert "macro_ingestion" in resp.json()["detail"]
