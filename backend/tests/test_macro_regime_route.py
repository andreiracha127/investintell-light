"""Tests for GET /macro/regime (detector vote2of3 — Frente B).

O endpoint serve o detector PROMOVIDO (composite por votos, worker
``regime_composite``, materializado em ``regime_composite_daily`` no cloud); o
Light só lê. Expõe estado binário + breakdown dos 3 votos (credit/trend/nfci).
Service stubbed at its canonical module — no live DB.
"""

import datetime as dt

import pytest
from httpx import ASGITransport, AsyncClient

from app.core.datalake import get_datalake_session
from app.main import create_app
from app.services import macro_regime as mr


def _client() -> AsyncClient:
    app = create_app()
    app.dependency_overrides[get_datalake_session] = lambda: None
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


def _snapshot(
    state: str = "risk_off",
    vote_count: int = 2,
    credit: bool = True,
    trend: bool = True,
    nfci: bool = False,
) -> mr.CompositeRegimeSnapshot:
    return mr.CompositeRegimeSnapshot(
        as_of=dt.date(2026, 6, 12),
        state=state,
        vote_count=vote_count,
        credit_vote=credit,
        trend_vote=trend,
        nfci_vote=nfci,
        ratio=0.7600,
        p20_5y=0.7901,
        nfci=-0.12,
        days_in_state=21,
        last_flip=dt.date(2026, 5, 22),
        recent_flips=[
            mr.RegimeFlip(date=dt.date(2026, 5, 22), state="risk_off"),
            mr.RegimeFlip(date=dt.date(2020, 6, 1), state="risk_on"),
        ],
        history=[
            mr.CompositeRegimePoint(
                date=dt.date(2026, 5, 21),
                state="risk_on",
                vote_count=1,
                credit_vote=True,
                trend_vote=False,
                nfci_vote=False,
                ratio=0.81,
                p20_5y=0.79,
                nfci=-0.2,
            ),
            mr.CompositeRegimePoint(
                date=dt.date(2026, 5, 22),
                state="risk_off",
                vote_count=2,
                credit_vote=True,
                trend_vote=True,
                nfci_vote=False,
                ratio=0.76,
                p20_5y=0.7901,
                nfci=-0.12,
            ),
        ],
    )


@pytest.mark.anyio
async def test_macro_regime_returns_state_and_vote_breakdown(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fake_fetch(datalake):
        return _snapshot()

    monkeypatch.setattr(mr, "fetch_composite_regime", fake_fetch)
    async with _client() as client:
        resp = await client.get("/macro/regime")
    assert resp.status_code == 200
    body = resp.json()
    assert body["detector"] == "vote2of3"
    assert body["state"] == "risk_off"
    assert body["vote_count"] == 2
    # breakdown dos 3 votos (explicabilidade)
    assert body["votes"] == {"credit": True, "trend": True, "nfci": False}
    # proveniência: voto de crédito (ratio vs p20) + valor do NFCI
    assert body["signal"]["ratio"] == 0.76
    assert body["signal"]["p20_5y"] == 0.7901
    assert body["signal"]["nfci"] == -0.12
    assert body["signal"]["distance_pct"] == pytest.approx(
        100.0 * (0.76 - 0.7901) / 0.7901, rel=1e-6
    )
    assert body["days_in_state"] == 21
    assert body["last_flip"] == "2026-05-22"
    assert [f["state"] for f in body["recent_flips"]] == ["risk_off", "risk_on"]
    assert [p["state"] for p in body["history"]] == ["risk_on", "risk_off"]
    assert body["history"][1]["votes"] == {"credit": True, "trend": True, "nfci": False}
    assert body["history"][1]["signal"]["distance_pct"] == pytest.approx(
        100.0 * (0.76 - 0.7901) / 0.7901, rel=1e-6
    )


@pytest.mark.anyio
async def test_macro_regime_risk_on_when_under_two_votes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fake_fetch(datalake):
        return _snapshot(state="risk_on", vote_count=1, credit=True, trend=False)

    monkeypatch.setattr(mr, "fetch_composite_regime", fake_fetch)
    async with _client() as client:
        resp = await client.get("/macro/regime")
    body = resp.json()
    assert body["state"] == "risk_on"
    assert body["vote_count"] == 1
    assert body["votes"]["trend"] is False


@pytest.mark.anyio
async def test_macro_regime_not_materialized_404(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fake_fetch(datalake):
        return None

    monkeypatch.setattr(mr, "fetch_composite_regime", fake_fetch)
    async with _client() as client:
        resp = await client.get("/macro/regime")
    assert resp.status_code == 404
    assert "regime_composite" in resp.json()["detail"]
