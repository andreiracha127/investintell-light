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


def _snapshot(
    state: str = "risk_on", stress_score: float | None = None
) -> mr.CreditRegimeSnapshot:
    return mr.CreditRegimeSnapshot(
        as_of=dt.date(2026, 6, 11),
        state=state,
        ratio=0.8412,
        p20_5y=0.7901,
        p_exit_5y=0.8012,
        stress_score=stress_score,
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


# ──────────────────────────────────────────────────────────────────────────────
# Modo low-drawdown (score graduado) — classificação por bandas do stress_score
# ──────────────────────────────────────────────────────────────────────────────
def test_graded_state_bands() -> None:
    assert mr.graded_state(None) == "risk_on"
    assert mr.graded_state(0.0) == "risk_on"
    assert mr.graded_state(24.9) == "risk_on"
    assert mr.graded_state(25.0) == "caution"
    assert mr.graded_state(49.9) == "caution"
    assert mr.graded_state(50.0) == "risk_off"
    assert mr.graded_state(100.0) == "risk_off"


@pytest.mark.anyio
async def test_macro_regime_binary_mode_is_default_and_unchanged(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Default = binário: stress_score na faixa de caution NÃO muda o state
    binário (o graded_state vem como info, mas o flip seco é preservado)."""

    async def fake_fetch(datalake):
        return _snapshot(state="risk_on", stress_score=30.0)

    monkeypatch.setattr(mr, "fetch_credit_regime", fake_fetch)
    async with _client() as client:
        resp = await client.get("/macro/regime")
    assert resp.status_code == 200
    body = resp.json()
    assert body["mode"] == "binary"
    assert body["state"] == "risk_on"          # binário, inalterado
    assert body["stress_score"] == 30.0
    assert body["graded_state"] == "caution"   # informativo


@pytest.mark.anyio
async def test_macro_regime_low_drawdown_mode_grades_to_caution(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fake_fetch(datalake):
        return _snapshot(state="risk_on", stress_score=30.0)

    monkeypatch.setattr(mr, "fetch_credit_regime", fake_fetch)
    async with _client() as client:
        resp = await client.get("/macro/regime?low_drawdown_mode=true")
    assert resp.status_code == 200
    body = resp.json()
    assert body["mode"] == "low_drawdown"
    assert body["state"] == "caution"          # estado intermediário graduado
    assert body["stress_score"] == 30.0
    assert body["bands"]["caution_score"] == 25.0
    assert body["bands"]["risk_off_score"] == 50.0


@pytest.mark.anyio
async def test_macro_regime_low_drawdown_risk_off_at_high_score(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fake_fetch(datalake):
        return _snapshot(state="risk_off", stress_score=72.0)

    monkeypatch.setattr(mr, "fetch_credit_regime", fake_fetch)
    async with _client() as client:
        resp = await client.get("/macro/regime?low_drawdown_mode=true")
    body = resp.json()
    assert body["state"] == "risk_off"
    assert body["graded_state"] == "risk_off"


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
