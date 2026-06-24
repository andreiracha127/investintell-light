"""Tests for the COMBO ``macro_quadrant`` block on GET /macro/regime (Sprint 4).

The route keeps the vote2of3 composite as the headline detector (decision O3)
and ADDS a ``macro_quadrant`` block read from ``regime_gate_daily`` via
``taa_bands.fetch_gate_regime`` (decision A — the worker materializes the
growth/inflation quadrant; the route reads it, never computes it). Both the
composite reader and the gate reader are stubbed at their canonical modules —
no live DB.

Task 8 retired ``combined_regime``/``effective_class_bands``/``goldfix_target``:
the block now exposes the ORTHOGONAL quadrant + per-sleeve ``policy_bands`` from
``QUADRANT_POLICIES["moderate"][quadrant]`` (informational display profile) and a
``haven_tilt`` that is ALWAYS ``None``. ``bands`` is empty when the quadrant is not
consumable (gate row absent or a non-quadrant value).
"""

import datetime as dt

import pytest
from httpx import ASGITransport, AsyncClient

from app.core.datalake import get_datalake_session
from app.main import create_app
from app.services import macro_regime as mr
from app.services import quadrant_policy as qp
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
    assert mq["gate"]["state"] == "risk_off"
    assert mq["gate"]["dwell_days"] == 30
    assert mq["gate"]["trend_vote"] is True
    assert mq["gate"]["credit_vote"] is True
    assert mq["gate"]["drawdown_vote"] is False
    # the worker-materialized quadrant is surfaced orthogonally to the gate.
    assert mq["quadrant"] == "slowdown"
    assert mq["growth_state"] == "down"
    assert mq["inflation_state"] == "up"
    # haven_tilt removed with goldfix; bands are the moderate/slowdown sleeve bands.
    assert mq["haven_tilt"] is None
    expected = qp.policy_bands(qp.QUADRANT_POLICIES["moderate"]["slowdown"])
    got = {b["asset_class"]: (b["min_weight"], b["max_weight"]) for b in mq["bands"]}
    assert set(got) == set(qp.STRUCTURAL_SLEEVES)
    for sleeve, (lo, hi) in expected.items():
        assert got[sleeve] == pytest.approx((lo, hi))


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
    # gate None + quadrant None => no consumable quadrant => empty bands, no haven.
    assert mq["bands"] == []
    assert mq["haven_tilt"] is None


def test_macro_quadrant_uses_sleeve_bands_not_goldfix(monkeypatch) -> None:
    """The macro block exposes per-sleeve bands from the quadrant policy and never
    a goldfix haven_tilt (removed). For a consumable slowdown quadrant, bands are
    the moderate/slowdown policy bands; haven_tilt is None."""
    import asyncio

    from app.api.routes import macro as macro_route
    from app.services import quadrant_policy as qp
    from app.services import taa_bands

    snap = taa_bands.GateRegimeSnapshot(
        as_of=__import__("datetime").date(2026, 1, 5), state="risk_on",
        vote_count=0, trend_vote=False, credit_vote=False, drawdown_vote=False,
        dwell_days=1, last_flip=None, growth_score=-0.01, inflation_score=0.02,
        quadrant="slowdown",
    )

    async def fake_gate(datalake):
        return snap

    monkeypatch.setattr(macro_route.taa_bands, "fetch_gate_regime", fake_gate)
    out = asyncio.run(macro_route._build_macro_quadrant(object()))
    assert out.haven_tilt is None
    expected = qp.policy_bands(qp.QUADRANT_POLICIES["moderate"]["slowdown"])
    got = {b.asset_class: (b.min_weight, b.max_weight) for b in out.bands}
    for sleeve, (lo, hi) in expected.items():
        assert got[sleeve] == (lo, hi)


def test_macro_quadrant_empty_bands_when_quadrant_none(monkeypatch) -> None:
    import asyncio

    from app.api.routes import macro as macro_route

    async def fake_gate(datalake):
        return None

    monkeypatch.setattr(macro_route.taa_bands, "fetch_gate_regime", fake_gate)
    out = asyncio.run(macro_route._build_macro_quadrant(object()))
    assert out.bands == []
    assert out.haven_tilt is None
