"""Tests for GET /macro/regime (Frente B re-escopada, ADENDO §6).

O detector (binário, stress de crédito HYG/IEF) é computado pelo worker
``credit_regime`` no repo datalake e materializado em ``credit_regime_daily``
no cloud; o Light só lê. O composite legado (``macro_regime_snapshot``) foi
REFUTADO pelo backtest e NÃO é consumido aqui. Service stubbed at its
canonical module — no live DB.
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


def _snapshot() -> mr.CreditRegimeSnapshot:
    return mr.CreditRegimeSnapshot(
        as_of=dt.date(2026, 6, 11),
        state="risk_on",
        ratio=0.8412,
        p20_5y=0.7901,
        hyg_close=79.11,
        ief_close=94.05,
        n_window=1260,
        days_in_state=1490,
        last_flip=dt.date(2020, 7, 14),
        recent_flips=[
            mr.RegimeFlip(date=dt.date(2020, 7, 14), state="risk_on"),
            mr.RegimeFlip(date=dt.date(2020, 3, 9), state="risk_off"),
        ],
    )


@pytest.mark.anyio
async def test_macro_regime_returns_state_and_explainability(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fake_fetch(datalake):
        return _snapshot()

    monkeypatch.setattr(mr, "fetch_credit_regime", fake_fetch)
    async with _client() as client:
        resp = await client.get("/macro/regime")
    assert resp.status_code == 200
    body = resp.json()
    assert body["state"] == "risk_on"
    assert body["as_of"] == "2026-06-11"
    # explicabilidade: ratio vs threshold + proveniência dos preços
    assert body["signal"]["ratio"] == 0.8412
    assert body["signal"]["p20_5y"] == 0.7901
    assert body["signal"]["hyg_close"] == 79.11
    assert body["signal"]["distance_pct"] == pytest.approx(
        100.0 * (0.8412 - 0.7901) / 0.7901, rel=1e-6
    )
    assert body["days_in_state"] == 1490
    assert body["last_flip"] == "2020-07-14"
    assert [f["state"] for f in body["recent_flips"]] == ["risk_on", "risk_off"]
    # contrato: a fonte é o detector validado, não o composite legado
    assert body["detector"] == "credit_stress_hyg_ief_p20_5y"


@pytest.mark.anyio
async def test_macro_regime_not_materialized_404(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fake_fetch(datalake):
        return None

    monkeypatch.setattr(mr, "fetch_credit_regime", fake_fetch)
    async with _client() as client:
        resp = await client.get("/macro/regime")
    assert resp.status_code == 404
    assert "credit_regime" in resp.json()["detail"]
