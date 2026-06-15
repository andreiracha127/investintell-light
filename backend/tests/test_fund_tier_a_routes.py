"""Tests for P4 Backend Tier A fund dossier endpoints.

Services are stubbed at ``app.services.fund_analysis``; no live DB or data lake.
"""

import datetime as dt
import uuid
from typing import Any

import pytest
from httpx import ASGITransport, AsyncClient

from app.core.datalake import get_datalake_session
from app.core.db import get_session
from app.main import create_app
from app.schemas.analysis import DatedValue, DrawdownOut, HistogramOut
from app.schemas.fund_analysis import (
    FundAnalysisHeader,
    FundAnalysisParams,
    FundAnalysisResponse,
    FundAnalysisStats,
    FundHoldingsTopResponse,
    FundPeerItem,
    FundPeersResponse,
    FundScatterResponse,
    FundSectorExposure,
    FundTopHolding,
)
from app.services import fund_analysis as fa

_FUND_ID = uuid.UUID("00000000-0000-0000-0000-000000000001")


def _client() -> AsyncClient:
    app = create_app()
    app.dependency_overrides[get_session] = lambda: None
    app.dependency_overrides[get_datalake_session] = lambda: None
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


def _analysis_payload() -> FundAnalysisResponse:
    return FundAnalysisResponse(
        params=FundAnalysisParams(
            range="1Y",
            window=63,
            start_date=dt.date(2025, 6, 12),
            end_date=dt.date(2026, 6, 12),
        ),
        header=FundAnalysisHeader(
            instrument_id=_FUND_ID,
            ticker="VFINX",
            name="Vanguard 500 Index Fund",
            last_nav=125.0,
            prev_nav=124.0,
            change=1.0,
            change_pct=1.0 / 124.0,
            as_of=dt.date(2026, 6, 12),
        ),
        growth_of_100=[(dt.date(2025, 6, 12), 100.0)],
        monthly_returns=[(dt.date(2026, 5, 31), 0.02)],
        rolling_volatility=[(dt.date(2026, 6, 12), 0.12)],
        rolling_sharpe=[(dt.date(2026, 6, 12), 1.1)],
        drawdown=[(dt.date(2026, 6, 12), -0.03)],
        histogram=HistogramOut(
            bin_edges=[-0.02, 0.0, 0.02],
            counts=[3, 7],
            counts_normalized=[0.3, 1.0],
        ),
        stats=FundAnalysisStats(
            annualized_volatility=0.12,
            var_95=0.015,
            cvar_95=0.02,
            total_return=0.25,
            max_drawdown=DrawdownOut(
                depth=-0.08,
                peak_date=dt.date(2026, 1, 1),
                trough_date=dt.date(2026, 3, 1),
            ),
            best_day=DatedValue(date=dt.date(2026, 4, 1), value=0.03),
            worst_day=DatedValue(date=dt.date(2026, 5, 1), value=-0.025),
        ),
    )


def _holdings_payload() -> FundHoldingsTopResponse:
    return FundHoldingsTopResponse(
        instrument_id=_FUND_ID,
        series_id="S000012345",
        report_date=dt.date(2026, 5, 31),
        top_holdings=[
            FundTopHolding(
                rank=1,
                issuer_name="Apple Inc",
                cusip="037833100",
                isin="US0378331005",
                asset_class="EC",
                sector="CORP",
                gics_sector=None,
                sector_label="Technology",
                market_value=10_000_000.0,
                pct_of_nav=6.1,
            )
        ],
        sector_breakdown=[
            FundSectorExposure(
                key="Technology",
                label="Technology",
                direct_pct=50.0,
                indirect_pct=0.0,
                total_pct=50.0,
                source="holdings",
            )
        ],
        pct_of_nav_total=6.1,
    )


def _peers_payload() -> FundPeersResponse:
    return FundPeersResponse(
        instrument_id=_FUND_ID,
        cohort_label="Large Blend",
        count=1,
        items=[
            FundPeerItem(
                instrument_id=_FUND_ID,
                ticker="VFINX",
                name="Vanguard 500 Index Fund",
                strategy_label="Large Blend",
                expense_ratio=0.0001,
                return_1y=0.24,
                volatility_1y=0.12,
                sharpe_1y=1.5,
                max_drawdown_1y=-0.08,
                cvar_95_12m=-0.02,
                is_target=True,
            )
        ],
    )


def _scatter_payload() -> FundScatterResponse:
    return FundScatterResponse(
        count=1,
        instrument_ids=[_FUND_ID],
        names=["Vanguard 500 Index Fund"],
        tickers=["VFINX"],
        expected_returns=[0.24],
        volatilities=[0.12],
        tail_risks=[-0.02],
        strategies=["Large Blend"],
    )


async def test_fund_analysis_success(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: dict[str, Any] = {}

    async def fake_fetch(session, instrument_id, *, range_key, window, max_points):
        seen.update(
            instrument_id=instrument_id,
            range_key=range_key,
            window=window,
            max_points=max_points,
        )
        return _analysis_payload()

    monkeypatch.setattr(fa, "fetch_fund_analysis", fake_fetch)
    async with _client() as client:
        resp = await client.get(
            f"/funds/{_FUND_ID}/analysis", params={"range": "1Y", "window": 63}
        )
    assert resp.status_code == 200
    body = resp.json()
    assert body["header"]["ticker"] == "VFINX"
    assert body["params"]["window"] == 63
    assert seen["instrument_id"] == _FUND_ID
    assert seen["range_key"] == "1Y"


async def test_fund_analysis_missing_fund_404(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_fetch(*args, **kwargs):
        return None

    monkeypatch.setattr(fa, "fetch_fund_analysis", fake_fetch)
    async with _client() as client:
        resp = await client.get(f"/funds/{_FUND_ID}/analysis")
    assert resp.status_code == 404


async def test_fund_analysis_insufficient_data_422(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fake_fetch(*args, **kwargs):
        raise fa.InsufficientFundDataError("Only 3 in-range daily returns")

    monkeypatch.setattr(fa, "fetch_fund_analysis", fake_fetch)
    async with _client() as client:
        resp = await client.get(f"/funds/{_FUND_ID}/analysis")
    assert resp.status_code == 422
    assert "Only 3" in resp.json()["detail"]


@pytest.mark.parametrize("window", [9, 253])
async def test_fund_analysis_window_bounds(window: int) -> None:
    async with _client() as client:
        resp = await client.get(f"/funds/{_FUND_ID}/analysis", params={"window": window})
    assert resp.status_code == 422


async def test_fund_holdings_top_success(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: dict[str, Any] = {}

    async def fake_fetch(session, datalake, instrument_id, *, limit):
        seen.update(instrument_id=instrument_id, limit=limit)
        return _holdings_payload()

    monkeypatch.setattr(fa, "fetch_fund_holdings_top", fake_fetch)
    async with _client() as client:
        resp = await client.get(f"/funds/{_FUND_ID}/holdings/top", params={"limit": 25})
    assert resp.status_code == 200
    body = resp.json()
    assert body["sector_breakdown"][0]["source"] == "holdings"
    assert body["top_holdings"][0]["issuer_name"] == "Apple Inc"
    assert seen == {"instrument_id": _FUND_ID, "limit": 25}


async def test_fund_holdings_top_missing_fund_404(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fake_fetch(*args, **kwargs):
        return None

    monkeypatch.setattr(fa, "fetch_fund_holdings_top", fake_fetch)
    async with _client() as client:
        resp = await client.get(f"/funds/{_FUND_ID}/holdings/top")
    assert resp.status_code == 404


@pytest.mark.parametrize("limit", [0, 51])
async def test_fund_holdings_top_limit_bounds(limit: int) -> None:
    async with _client() as client:
        resp = await client.get(f"/funds/{_FUND_ID}/holdings/top", params={"limit": limit})
    assert resp.status_code == 422


async def test_fund_peers_success(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: dict[str, Any] = {}

    async def fake_fetch(session, instrument_id, *, limit):
        seen.update(instrument_id=instrument_id, limit=limit)
        return _peers_payload()

    monkeypatch.setattr(fa, "fetch_fund_peers", fake_fetch)
    async with _client() as client:
        resp = await client.get(f"/funds/{_FUND_ID}/peers", params={"limit": 10})
    assert resp.status_code == 200
    body = resp.json()
    assert body["cohort_label"] == "Large Blend"
    assert body["items"][0]["is_target"] is True
    assert seen == {"instrument_id": _FUND_ID, "limit": 10}


async def test_fund_peers_missing_fund_404(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_fetch(*args, **kwargs):
        return None

    monkeypatch.setattr(fa, "fetch_fund_peers", fake_fetch)
    async with _client() as client:
        resp = await client.get(f"/funds/{_FUND_ID}/peers")
    assert resp.status_code == 404


@pytest.mark.parametrize("limit", [0, 51])
async def test_fund_peers_limit_bounds(limit: int) -> None:
    async with _client() as client:
        resp = await client.get(f"/funds/{_FUND_ID}/peers", params={"limit": limit})
    assert resp.status_code == 422


async def test_funds_scatter_success(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: dict[str, Any] = {}

    async def fake_fetch(session, *, limit):
        seen["limit"] = limit
        return _scatter_payload()

    monkeypatch.setattr(fa, "fetch_funds_scatter", fake_fetch)
    async with _client() as client:
        resp = await client.get("/funds/scatter", params={"limit": 100})
    assert resp.status_code == 200
    body = resp.json()
    assert body["count"] == 1
    assert body["instrument_ids"] == [str(_FUND_ID)]
    assert body["expected_returns"] == [0.24]
    assert seen == {"limit": 100}


@pytest.mark.parametrize("limit", [0, 501])
async def test_funds_scatter_limit_bounds(limit: int) -> None:
    async with _client() as client:
        resp = await client.get("/funds/scatter", params={"limit": limit})
    assert resp.status_code == 422
