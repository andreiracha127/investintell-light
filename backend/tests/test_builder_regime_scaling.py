"""COMBO Sprint 3 — Task 4: the CVaR-scaling regime read uses the live GATE.

The ``max_return_cvar`` path scales its CVaR ceiling by the regime state. Sprint
3 switches that read from credit-only (``macro_regime.fetch_credit_regime``) to
the live gate (``taa_bands.fetch_gate_regime``). These tests force the gate via
the monkeypatch seam (the read is datalake-guarded, so a non-None dummy datalake
is injected) and confirm the scaling now follows the gate, not the credit read.
"""

import datetime as dt
import uuid
from typing import Any

import numpy as np
import pandas as pd
import pytest
from httpx import ASGITransport, AsyncClient

from app.core.datalake import get_optional_datalake_session
from app.core.db import get_session
from app.main import create_app
from app.optimizer import data as optimizer_data
from app.services import macro_regime
from app.services import taa_bands as tb

_IDS = [uuid.UUID(f"00000000-0000-0000-0000-00000000000{i}") for i in range(1, 4)]


def _gate(state: str) -> tb.GateRegimeSnapshot:
    return tb.GateRegimeSnapshot(
        as_of=dt.date(2026, 6, 20),
        state=state,
        vote_count=2 if state == "risk_off" else 0,
        trend_vote=state == "risk_off",
        credit_vote=state == "risk_off",
        drawdown_vote=False,
        dwell_days=30,
        last_flip=None,
        growth_score=None,
        inflation_score=None,
        quadrant=None,
    )


def _client() -> AsyncClient:
    app = create_app()
    app.dependency_overrides[get_session] = lambda: None
    app.dependency_overrides[get_optional_datalake_session] = lambda: object()
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


def _stub_loaders(monkeypatch: pytest.MonkeyPatch) -> None:
    n_obs = 400
    index = pd.bdate_range("2024-01-02", periods=n_obs)
    rng = np.random.default_rng(17)

    async def fake_load(session: Any, assets: Any, window_days: Any = None, today: Any = None):
        return pd.DataFrame(
            {ref.label: rng.normal(0.0004, 0.01, n_obs) for ref in assets}, index=index
        )

    async def fake_aum(session: Any, fund_ids: list[uuid.UUID]):
        return {fid: 1e9 * (i + 1) for i, fid in enumerate(fund_ids)}

    async def fake_class(session: Any, fund_ids: list[uuid.UUID]):
        return {fid: "equity" for fid in fund_ids}

    async def fake_strategy(session: Any, fund_ids: list[uuid.UUID]):
        return {fid: "Core" for fid in fund_ids}

    monkeypatch.setattr(optimizer_data, "load_aligned_returns", fake_load)
    monkeypatch.setattr(optimizer_data, "load_fund_aum", fake_aum)
    monkeypatch.setattr(optimizer_data, "load_fund_asset_class", fake_class)
    monkeypatch.setattr(optimizer_data, "load_fund_strategy_label", fake_strategy)


async def test_cvar_scaling_uses_gate_risk_off(monkeypatch: pytest.MonkeyPatch) -> None:
    """gate risk_off => the effective CVaR ceiling is halved (< the payload's)."""
    _stub_loaders(monkeypatch)
    monkeypatch.setattr(tb, "fetch_gate_regime", lambda *_a, **_k: _coro(_gate("risk_off")))
    payload = {
        "assets": [{"kind": "fund", "id": str(fid)} for fid in _IDS],
        "objective": "max_return_cvar",
        "cvar_limit": 0.02,
        "constraints": {"cap": 1.0},
    }
    async with _client() as client:
        resp = await client.post("/builder/optimize", json=payload)
    assert resp.status_code == 200, resp.text
    diag = resp.json()["diagnostics"]
    assert diag["regime_state"] == "risk_off"
    assert diag["cvar_limit_effective"] < 0.02
    assert diag["cvar_limit_effective"] == pytest.approx(0.01)


async def test_cvar_scaling_gate_risk_on_is_neutral(monkeypatch: pytest.MonkeyPatch) -> None:
    """gate risk_on => the ceiling is unchanged."""
    _stub_loaders(monkeypatch)
    monkeypatch.setattr(tb, "fetch_gate_regime", lambda *_a, **_k: _coro(_gate("risk_on")))
    payload = {
        "assets": [{"kind": "fund", "id": str(fid)} for fid in _IDS],
        "objective": "max_return_cvar",
        "cvar_limit": 0.02,
        "constraints": {"cap": 1.0},
    }
    async with _client() as client:
        resp = await client.post("/builder/optimize", json=payload)
    assert resp.status_code == 200, resp.text
    diag = resp.json()["diagnostics"]
    assert diag["regime_state"] == "risk_on"
    assert diag["cvar_limit_effective"] == pytest.approx(0.02)


async def test_cvar_scaling_no_longer_reads_credit(monkeypatch: pytest.MonkeyPatch) -> None:
    """The credit reader is NO LONGER consulted on the scaling path: even with
    credit forced risk_off, a gate risk_on leaves the ceiling unchanged."""
    _stub_loaders(monkeypatch)

    async def _boom(*_a: Any, **_k: Any):
        raise AssertionError("fetch_credit_regime must not be called on the scaling path")

    monkeypatch.setattr(macro_regime, "fetch_credit_regime", _boom)
    monkeypatch.setattr(tb, "fetch_gate_regime", lambda *_a, **_k: _coro(_gate("risk_on")))
    payload = {
        "assets": [{"kind": "fund", "id": str(fid)} for fid in _IDS],
        "objective": "max_return_cvar",
        "cvar_limit": 0.02,
        "constraints": {"cap": 1.0},
    }
    async with _client() as client:
        resp = await client.post("/builder/optimize", json=payload)
    assert resp.status_code == 200, resp.text
    diag = resp.json()["diagnostics"]
    assert diag["regime_state"] == "risk_on"
    assert diag["cvar_limit_effective"] == pytest.approx(0.02)


async def _coro(value: Any) -> Any:
    return value
