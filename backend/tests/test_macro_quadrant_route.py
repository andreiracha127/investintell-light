"""Tests for the COMBO ``macro_quadrant`` block on GET /macro/regime (Sprint 4).

The route keeps the vote2of3 composite as the headline detector (decision O3)
and ADDS a ``macro_quadrant`` block read from ``regime_gate_daily`` via
``taa_bands.fetch_gate_regime`` (decision A — the worker materializes the
growth/inflation quadrant; the route reads it, never computes it). Both the
composite reader and the gate reader are stubbed at their canonical modules —
no live DB.
"""

import datetime as dt

import pytest
from httpx import ASGITransport, AsyncClient

from app.core.datalake import get_datalake_session
from app.main import create_app
from app.services import macro_regime as mr
from app.services import taa_bands as tb


def _client() -> AsyncClient:
    app = create_app()
    app.dependency_overrides[get_datalake_session] = lambda: None
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


def _composite() -> mr.CompositeRegimeSnapshot:
    """Minimal composite snapshot so the route returns 200 (not 404)."""
    return mr.CompositeRegimeSnapshot(
        as_of=dt.date(2026, 6, 12),
        state="risk_on",
        vote_count=1,
        credit_vote=True,
        trend_vote=False,
        nfci_vote=False,
        ratio=0.81,
        p20_5y=0.79,
        nfci=-0.2,
        days_in_state=10,
        last_flip=dt.date(2026, 5, 22),
        recent_flips=[],
        history=[],
    )


@pytest.fixture(autouse=True)
def _seed_composite(monkeypatch: pytest.MonkeyPatch) -> None:
    """Make ``fetch_composite_regime`` return a snapshot so the route is 200."""

    async def _fetch(datalake):  # noqa: ANN001
        return _composite()

    monkeypatch.setattr(mr, "fetch_composite_regime", _fetch)


@pytest.mark.anyio
async def test_macro_regime_includes_gate_block(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def _gate(*a, **k):  # noqa: ANN002, ANN003
        return tb.GateRegimeSnapshot(
            as_of=dt.date(2026, 6, 18),
            state="risk_off",
            vote_count=2,
            trend_vote=True,
            credit_vote=True,
            drawdown_vote=False,
            dwell_days=30,
            last_flip=None,
            growth_score=-0.03,
            inflation_score=0.01,
            quadrant="slowdown",
        )

    monkeypatch.setattr(tb, "fetch_gate_regime", _gate)
    async with _client() as client:
        resp = await client.get("/macro/regime")
    assert resp.status_code == 200
    mq = resp.json()["macro_quadrant"]
    # gate risk_off dominates over the quadrant => combined regime RISK_OFF, 4 bands
    assert mq["combined_regime"] == "RISK_OFF"
    assert mq["gate"]["state"] == "risk_off"
    assert mq["gate"]["dwell_days"] == 30
    assert mq["gate"]["trend_vote"] is True
    assert mq["gate"]["credit_vote"] is True
    assert mq["gate"]["drawdown_vote"] is False
    # the worker-materialized quadrant is surfaced even when the gate dominates bands
    assert mq["quadrant"] == "slowdown"
    assert mq["growth_state"] == "down"
    assert mq["inflation_state"] == "up"
    assert mq["haven_tilt"] is None
    eq = next(b for b in mq["bands"] if b["asset_class"] == "equity")
    # RISK_OFF equity: center .38 hw .08*1.5=.12 -> [0.26, 0.50]
    assert abs(eq["min_weight"] - 0.26) < 1e-6
    assert abs(eq["max_weight"] - 0.50) < 1e-6


@pytest.mark.anyio
async def test_macro_regime_slowdown_quadrant_routes_to_haven(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # gate risk_on + worker-materialized SLOWDOWN => STAG_GOLD haven tilt (decision A)
    async def _gate(*a, **k):  # noqa: ANN002, ANN003
        return tb.GateRegimeSnapshot(
            as_of=dt.date(2026, 6, 18),
            state="risk_on",
            vote_count=0,
            trend_vote=False,
            credit_vote=False,
            drawdown_vote=False,
            dwell_days=80,
            last_flip=None,
            growth_score=-0.05,
            inflation_score=0.02,
            quadrant="slowdown",
        )

    monkeypatch.setattr(tb, "fetch_gate_regime", _gate)
    async with _client() as client:
        resp = await client.get("/macro/regime")
    mq = resp.json()["macro_quadrant"]
    assert mq["quadrant"] == "slowdown"
    assert mq["combined_regime"] == "STAG_GOLD"
    assert mq["bands"] == []  # haven bypasses class bands
    assert mq["haven_tilt"] and mq["haven_tilt"]["GLD"] > 0


@pytest.mark.anyio
async def test_macro_regime_gate_empty_degrades(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def _no_gate(*a, **k):  # noqa: ANN002, ANN003
        return None

    monkeypatch.setattr(tb, "fetch_gate_regime", _no_gate)
    async with _client() as client:
        resp = await client.get("/macro/regime")
    mq = resp.json()["macro_quadrant"]
    assert mq["gate"] is None
    assert mq["quadrant"] is None
    # gate None + quadrant None => combined regime RISK_ON, still 4 bands
    assert mq["combined_regime"] == "RISK_ON"
    assert len(mq["bands"]) == 4
