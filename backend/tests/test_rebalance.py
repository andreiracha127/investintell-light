"""Tests for Frente A — política de rebalanceamento (A1–A4).

Desenho (doc de research §2, espelhando a mecânica LEAN): gatilho calendário
e gatilho por banda são ortogonais; gatilho macro (frente B) é opcional por
política. Decisão:

  proposal     — calendário venceu OU gatilho macro disparou (job agendado
                 gera a proposta completa)
  drift_alert  — banda (abs ou rel) violada por alguma posição
  no_action    — caso contrário

NUNCA auto-executa (produto é advisory): o evaluator/preview apenas computa
proposta + diff + turnover. Pesos-alvo vêm do MESMO serviço de otimização do
builder (``app.services.portfolio_builder.run_optimize``, min-CVaR default).
"""

import datetime as dt
import uuid
from types import SimpleNamespace

import pytest
from httpx import ASGITransport, AsyncClient

from app.core.auth import CurrentUser, get_current_user
from app.core.datalake import get_optional_datalake_session
from app.core.db import get_session
from app.main import create_app
from app.rebalance import evaluator as ev
from app.services import portfolio_builder, portfolio_crud

NOW = dt.datetime(2026, 6, 12, 12, 0, tzinfo=dt.UTC)


# ---------------------------------------------------------------------------
# calendar_due
# ---------------------------------------------------------------------------


def test_calendar_due_when_never_evaluated() -> None:
    assert ev.calendar_due(None, "monthly", NOW) is True


@pytest.mark.parametrize(
    ("frequency", "days", "due"),
    [
        ("weekly", 6, False), ("weekly", 7, True),
        ("monthly", 29, False), ("monthly", 30, True),
        ("quarterly", 90, False), ("quarterly", 91, True),
    ],
)
def test_calendar_due_frequencies(frequency: str, days: int, due: bool) -> None:
    last = NOW - dt.timedelta(days=days)
    assert ev.calendar_due(last, frequency, NOW) is due


def test_calendar_due_rejects_unknown_frequency() -> None:
    with pytest.raises(KeyError):
        ev.calendar_due(None, "daily", NOW)


# ---------------------------------------------------------------------------
# macro trigger
# ---------------------------------------------------------------------------


def test_macro_trigger_requires_enabled_and_risk_off() -> None:
    flip = dt.date(2026, 6, 1)
    assert ev.macro_triggered(False, "risk_off", flip, None) is False
    assert ev.macro_triggered(True, "risk_on", flip, None) is False
    assert ev.macro_triggered(True, "risk_off", flip, None) is True


def test_macro_trigger_fires_only_for_unprocessed_flip() -> None:
    flip = dt.date(2026, 6, 1)
    before = dt.datetime(2026, 5, 20, tzinfo=dt.UTC)
    after = dt.datetime(2026, 6, 5, tzinfo=dt.UTC)
    assert ev.macro_triggered(True, "risk_off", flip, before) is True
    # flip já processado numa avaliação posterior a ele → não re-dispara
    assert ev.macro_triggered(True, "risk_off", flip, after) is False


# ---------------------------------------------------------------------------
# drifts / decisão / turnover
# ---------------------------------------------------------------------------


def test_compute_drifts_flags_abs_and_rel_breaches() -> None:
    current = {"VTI": 0.50, "AGG": 0.28, "GLD": 0.22}
    target = {"VTI": 0.44, "AGG": 0.36, "GLD": 0.20}
    drifts = ev.compute_drifts(current, target, band_abs=0.05, band_rel=0.25)
    by = {d.ticker: d for d in drifts}
    # VTI: |0.06| > 0.05 → breach abs
    assert by["VTI"].drift_abs == pytest.approx(0.06)
    assert by["VTI"].breach is True
    # AGG: |−0.08| > 0.05 e rel 0.08/0.36=22% < 25% → breach (abs)
    assert by["AGG"].breach is True
    # GLD: |0.02| < 0.05 e rel 10% < 25% → ok
    assert by["GLD"].breach is False
    assert by["GLD"].drift_rel == pytest.approx(0.10)


def test_compute_drifts_rel_only_breach() -> None:
    # peso-alvo pequeno: 3pp de drift = 60% do alvo → viola a banda relativa
    drifts = ev.compute_drifts(
        {"X": 0.08, "Y": 0.92}, {"X": 0.05, "Y": 0.95},
        band_abs=0.05, band_rel=0.25,
    )
    x = next(d for d in drifts if d.ticker == "X")
    assert abs(x.drift_abs) < 0.05
    assert x.drift_rel == pytest.approx(0.60)
    assert x.breach is True


def test_decide_precedence() -> None:
    breached = [SimpleNamespace(breach=True)]
    clean = [SimpleNamespace(breach=False)]
    assert ev.decide(clean, calendar_is_due=False, macro_is_triggered=False) == "no_action"
    assert ev.decide(breached, calendar_is_due=False, macro_is_triggered=False) == "drift_alert"
    assert ev.decide(clean, calendar_is_due=True, macro_is_triggered=False) == "proposal"
    assert ev.decide(breached, calendar_is_due=False, macro_is_triggered=True) == "proposal"
    # calendário vence sobre alerta
    assert ev.decide(breached, calendar_is_due=True, macro_is_triggered=False) == "proposal"


def test_turnover_is_half_sum_of_abs_diffs() -> None:
    drifts = [
        SimpleNamespace(drift_abs=0.06), SimpleNamespace(drift_abs=-0.08),
        SimpleNamespace(drift_abs=0.02),
    ]
    assert ev.turnover_pct(drifts) == pytest.approx(8.0)  # 0.5×0.16×100


def test_viable_cap_widens_for_small_portfolios() -> None:
    assert ev.viable_cap(2) == pytest.approx(0.5, abs=1e-6)
    assert ev.viable_cap(3) == pytest.approx(1.0 / 3.0, abs=1e-3)
    assert ev.viable_cap(4) == 0.25
    assert ev.viable_cap(10) == 0.25


# ---------------------------------------------------------------------------
# GET /portfolios/{id}/rebalance/preview (stubs at canonical modules)
# ---------------------------------------------------------------------------


def _position(ticker: str, quantity: float) -> SimpleNamespace:
    return SimpleNamespace(
        ticker=ticker, quantity=quantity, acq_price=None, basis="reference",
        commission=None, trade_date=None,
    )


def _client() -> AsyncClient:
    app = create_app()
    app.dependency_overrides[get_session] = lambda: None
    app.dependency_overrides[get_optional_datalake_session] = lambda: None
    app.dependency_overrides[get_current_user] = lambda: CurrentUser(
        sub="u-1", org_id=None, claims={}
    )
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


_FUND_ID = uuid.UUID("00000000-0000-0000-0000-00000000000a")


def _stub_pricing(monkeypatch: pytest.MonkeyPatch, portfolio) -> None:
    async def fake_get_portfolio(session, portfolio_id, owner_sub=None):
        return portfolio

    async def fake_fund_ids(session, tickers):
        return {"FUNDX": _FUND_ID}

    async def fake_closes(session, tickers):
        return {"AAPL": [(dt.date(2026, 6, 11), 100.0)]}

    async def fake_navs(session, tickers):
        return {"FUNDX": [(dt.date(2026, 6, 11), 50.0)]}

    monkeypatch.setattr(portfolio_crud, "get_portfolio", fake_get_portfolio)
    monkeypatch.setattr(ev, "fund_instrument_ids_by_ticker", fake_fund_ids)
    monkeypatch.setattr(portfolio_crud, "select_last_two_closes", fake_closes)
    monkeypatch.setattr(portfolio_crud, "select_last_two_navs", fake_navs)


def _stub_optimizer(monkeypatch: pytest.MonkeyPatch, weights: dict) -> dict:
    captured: dict = {}

    async def fake_run_optimize(session, payload):
        captured["payload"] = payload
        outs = []
        for asset in payload.assets:
            key = str(asset.id) if asset.kind == "fund" else asset.ticker
            outs.append(SimpleNamespace(asset=asset, weight=weights[key]))
        return SimpleNamespace(
            weights=outs, diagnostics=SimpleNamespace(status="optimal")
        )

    monkeypatch.setattr(portfolio_builder, "run_optimize", fake_run_optimize)
    return captured


@pytest.mark.anyio
async def test_preview_no_policy_uses_defaults_and_reports_drift(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    portfolio = SimpleNamespace(
        id=7, name="P", cash=0.0,
        positions=[_position("FUNDX", 120.0), _position("AAPL", 40.0)],
    )
    _stub_pricing(monkeypatch, portfolio)
    # mv: FUNDX 6000 (60%), AAPL 4000 (40%); alvo 50/50 → drift 10pp > 5pp
    captured = _stub_optimizer(
        monkeypatch, {str(_FUND_ID): 0.50, "AAPL": 0.50}
    )

    async def fake_get_policy(session, portfolio_id):
        return None

    monkeypatch.setattr(ev, "get_policy", fake_get_policy)

    async with _client() as client:
        resp = await client.get("/portfolios/7/rebalance/preview")
    assert resp.status_code == 200
    body = resp.json()
    # sem política salva e nunca avaliado → calendário vence → proposal
    assert body["decision"] == "proposal"
    assert body["policy"]["frequency"] == "monthly"
    assert body["policy"]["band_abs"] == 0.05
    assert body["policy"]["is_default"] is True
    drifts = {d["ticker"]: d for d in body["drifts"]}
    assert drifts["FUNDX"]["current_weight"] == pytest.approx(0.60)
    assert drifts["FUNDX"]["target_weight"] == pytest.approx(0.50)
    assert drifts["FUNDX"]["breach"] is True
    assert body["proposal"]["turnover_pct"] == pytest.approx(10.0)
    assert body["proposal"]["objective"] == "min_cvar"
    # A4: o optimizer foi chamado com o MESMO contrato do builder
    payload = captured["payload"]
    assert payload.objective == "min_cvar"
    kinds = {a.kind for a in payload.assets}
    assert kinds == {"fund", "equity"}
    # nunca auto-executa: resposta é proposta, sem efeitos colaterais
    assert "executed" not in body


@pytest.mark.anyio
async def test_preview_within_bands_no_action(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    portfolio = SimpleNamespace(
        id=7, name="P", cash=0.0,
        positions=[_position("FUNDX", 100.0), _position("AAPL", 50.0)],
    )
    _stub_pricing(monkeypatch, portfolio)
    # mv: FUNDX 5000 (50%), AAPL 5000 (50%); alvo 52/48 → drift 2pp, rel 3.8%
    _stub_optimizer(monkeypatch, {str(_FUND_ID): 0.52, "AAPL": 0.48})

    async def fake_get_policy(session, portfolio_id):
        return SimpleNamespace(
            portfolio_id=7, frequency="monthly", band_abs=0.05, band_rel=0.25,
            macro_trigger_enabled=False,
            last_evaluated_at=NOW - dt.timedelta(days=2),
        )

    monkeypatch.setattr(ev, "get_policy", fake_get_policy)

    async with _client() as client:
        resp = await client.get("/portfolios/7/rebalance/preview")
    assert resp.status_code == 200
    body = resp.json()
    assert body["decision"] == "no_action"
    assert body["calendar_due"] is False
    assert body["macro_triggered"] is False
    assert body["policy"]["is_default"] is False


@pytest.mark.anyio
async def test_preview_macro_trigger_forces_proposal(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    portfolio = SimpleNamespace(
        id=7, name="P", cash=0.0,
        positions=[_position("FUNDX", 100.0), _position("AAPL", 50.0)],
    )
    _stub_pricing(monkeypatch, portfolio)
    _stub_optimizer(monkeypatch, {str(_FUND_ID): 0.50, "AAPL": 0.50})

    async def fake_get_policy(session, portfolio_id):
        return SimpleNamespace(
            portfolio_id=7, frequency="monthly", band_abs=0.30, band_rel=0.90,
            macro_trigger_enabled=True,
            last_evaluated_at=NOW - dt.timedelta(days=2),
        )

    async def fake_regime(datalake):
        return SimpleNamespace(state="risk_off", last_flip=dt.date(2026, 6, 11))

    monkeypatch.setattr(ev, "get_policy", fake_get_policy)
    monkeypatch.setattr(ev, "fetch_regime_state", fake_regime)

    async with _client() as client:
        resp = await client.get("/portfolios/7/rebalance/preview")
    assert resp.status_code == 200
    body = resp.json()
    assert body["macro_triggered"] is True
    assert body["decision"] == "proposal"


@pytest.mark.anyio
async def test_preview_unknown_portfolio_404(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fake_get_portfolio(session, portfolio_id, owner_sub=None):
        return None

    monkeypatch.setattr(portfolio_crud, "get_portfolio", fake_get_portfolio)
    async with _client() as client:
        resp = await client.get("/portfolios/99/rebalance/preview")
    assert resp.status_code == 404


@pytest.mark.anyio
async def test_preview_single_position_422(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    portfolio = SimpleNamespace(
        id=7, name="P", cash=0.0, positions=[_position("AAPL", 10.0)],
    )
    _stub_pricing(monkeypatch, portfolio)

    async def fake_get_policy(session, portfolio_id):
        return None

    monkeypatch.setattr(ev, "get_policy", fake_get_policy)
    async with _client() as client:
        resp = await client.get("/portfolios/7/rebalance/preview")
    assert resp.status_code == 422


# ---------------------------------------------------------------------------
# PUT/GET /portfolios/{id}/rebalance/policy
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_put_and_get_policy_roundtrip(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    stored: dict = {}

    async def fake_get_portfolio_exists(session, portfolio_id, owner_sub=None):
        return True

    async def fake_upsert(session, portfolio_id, **fields):
        stored.update({"portfolio_id": portfolio_id, **fields})
        return SimpleNamespace(
            portfolio_id=portfolio_id, last_evaluated_at=None, **fields
        )

    async def fake_get_policy(session, portfolio_id):
        if not stored:
            return None
        return SimpleNamespace(last_evaluated_at=None, **stored)

    monkeypatch.setattr(portfolio_crud, "portfolio_exists", fake_get_portfolio_exists)
    monkeypatch.setattr(ev, "upsert_policy", fake_upsert)
    monkeypatch.setattr(ev, "get_policy", fake_get_policy)

    async with _client() as client:
        resp = await client.get("/portfolios/7/rebalance/policy")
        assert resp.status_code == 404

        resp = await client.put(
            "/portfolios/7/rebalance/policy",
            json={
                "frequency": "quarterly", "band_abs": 0.04, "band_rel": 0.20,
                "macro_trigger_enabled": True,
            },
        )
        assert resp.status_code == 200
        assert resp.json()["frequency"] == "quarterly"
        assert resp.json()["macro_trigger_enabled"] is True

        resp = await client.get("/portfolios/7/rebalance/policy")
        assert resp.status_code == 200
        assert resp.json()["band_abs"] == 0.04


@pytest.mark.anyio
async def test_put_policy_validates_bands(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fake_get_portfolio_exists(session, portfolio_id, owner_sub=None):
        return True

    monkeypatch.setattr(portfolio_crud, "portfolio_exists", fake_get_portfolio_exists)
    async with _client() as client:
        resp = await client.put(
            "/portfolios/7/rebalance/policy",
            json={"frequency": "daily", "band_abs": 0.05, "band_rel": 0.25,
                  "macro_trigger_enabled": False},
        )
        assert resp.status_code == 422
        resp = await client.put(
            "/portfolios/7/rebalance/policy",
            json={"frequency": "monthly", "band_abs": -0.01, "band_rel": 0.25,
                  "macro_trigger_enabled": False},
        )
        assert resp.status_code == 422


# ---------------------------------------------------------------------------
# T3D-1 — two-tier drift classification (ok / maintenance / urgent)
# ---------------------------------------------------------------------------


def test_drift_status_default_urgent_is_twice_band_abs() -> None:
    assert ev.default_urgent_band(0.05) == pytest.approx(0.10)
    assert ev.default_urgent_band(0.25) == pytest.approx(0.50)
    # never exceeds a full 100% drift
    assert ev.default_urgent_band(0.60) == pytest.approx(1.0)


def test_compute_drifts_classifies_three_tiers() -> None:
    current = {"OK": 0.41, "MAINT": 0.47, "URG": 0.62}
    target = {"OK": 0.40, "MAINT": 0.40, "URG": 0.40}
    drifts = ev.compute_drifts(
        current, target, band_abs=0.05, band_rel=0.25, band_urgent=0.10
    )
    by = {d.ticker: d for d in drifts}
    # |0.01| < 0.05 -> ok, not a breach
    assert by["OK"].status == "ok"
    assert by["OK"].breach is False
    # 0.05 <= |0.07| < 0.10 -> maintenance, still a breach
    assert by["MAINT"].status == "maintenance"
    assert by["MAINT"].breach is True
    # |0.22| >= 0.10 -> urgent, a breach
    assert by["URG"].status == "urgent"
    assert by["URG"].breach is True


def test_compute_drifts_status_boundaries_are_inclusive() -> None:
    # exactly at the maintenance band -> maintenance; exactly at urgent -> urgent
    drifts = ev.compute_drifts(
        {"M": 0.45, "U": 0.50}, {"M": 0.40, "U": 0.40},
        band_abs=0.05, band_rel=10.0, band_urgent=0.10,
    )
    by = {d.ticker: d for d in drifts}
    assert by["M"].status == "maintenance"  # |0.05| == band_abs (inclusive)
    assert by["U"].status == "urgent"       # |0.10| == band_urgent (inclusive)


def test_compute_drifts_relative_only_breach_is_maintenance() -> None:
    # small abs drift but big relative drift -> breach, classified maintenance
    drifts = ev.compute_drifts(
        {"X": 0.08, "Y": 0.92}, {"X": 0.05, "Y": 0.95},
        band_abs=0.05, band_rel=0.25, band_urgent=0.10,
    )
    x = next(d for d in drifts if d.ticker == "X")
    assert abs(x.drift_abs) < 0.05          # below the absolute maintenance band
    assert x.drift_rel == pytest.approx(0.60)
    assert x.breach is True
    assert x.status == "maintenance"


def test_compute_drifts_defaults_urgent_when_band_urgent_omitted() -> None:
    # band_urgent omitted -> defaults to 2 x band_abs (= 0.10 here)
    drifts = ev.compute_drifts(
        {"A": 0.62}, {"A": 0.40}, band_abs=0.05, band_rel=0.25
    )
    assert drifts[0].status == "urgent"
