"""COMBO Sprint 3 — Tasks 2 & 3: regime BlockBudgets + the ``combo`` dispatch.

These tests run the optimizer LIVE (real cvxpy solve); only the data loaders and
the gate reader are stubbed — the same seam ``test_builder_block_budgets.py`` and
``test_builder_regime_cvar.py`` use. ``fetch_gate_regime`` is monkeypatched to
drive the regime/quadrant deterministically (it is the single source of truth —
decision A), and ``load_fund_asset_class`` returns DISTINCT classes so the
regime bands map onto real column groups.
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
from app.schemas.builder import EquityRefIn, FundRefIn
from app.services import portfolio_builder as pb
from app.services import taa_bands as tb

# Four funds spanning the COMBO band classes: equity / fixed_income /
# alternatives / cash. A fifth name (a GLD equity) feeds the goldfix haven.
_FUND_IDS = [uuid.UUID(f"00000000-0000-0000-0000-00000000000{i}") for i in range(1, 5)]
_CLASS_OF = {
    _FUND_IDS[0]: "equity",
    _FUND_IDS[1]: "fixed_income",
    _FUND_IDS[2]: "alternatives",
    _FUND_IDS[3]: "cash",
}


def _gate_snapshot(*, state: str = "risk_on", quadrant: str | None = None) -> tb.GateRegimeSnapshot:
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
        quadrant=quadrant,
    )


def _async(value: Any):
    async def _f(*_a: Any, **_k: Any) -> Any:
        return value

    return _f


# ── Task 2: _resolve_regime_block_budgets ────────────────────────────────────


async def test_combo_builds_riskon_blocks(monkeypatch: pytest.MonkeyPatch) -> None:
    """Gate risk_on + no quadrant => RISK_ON bands; equity block is
    [center .52 ± hw .08*1.5] clamped by IPS => [0.40, 0.64]."""
    monkeypatch.setattr(
        optimizer_data,
        "load_fund_asset_class",
        _async({fid: _CLASS_OF[fid] for fid in _CLASS_OF}),
    )
    monkeypatch.setattr(tb, "fetch_gate_regime", _async(_gate_snapshot(state="risk_on")))
    assets = [FundRefIn(kind="fund", id=fid) for fid in _FUND_IDS]
    labels = [f"fund:{fid}" for fid in _FUND_IDS]
    blocks, regime, quad = await pb._resolve_regime_block_budgets(
        session=None, datalake=object(), assets=assets, labels=labels  # type: ignore[arg-type]
    )
    assert regime == "RISK_ON"
    assert quad is None
    eq = next(b for b in blocks if 0 in b.indices)
    assert abs(eq.lo - 0.40) < 1e-9 and abs(eq.hi - 0.64) < 1e-9
    # fixed_income center .30 ± .06*1.5=.09 -> [0.21, 0.39]
    fi = next(b for b in blocks if 1 in b.indices)
    assert abs(fi.lo - 0.21) < 1e-9 and abs(fi.hi - 0.39) < 1e-9


async def test_combo_riskoff_gate_dominates(monkeypatch: pytest.MonkeyPatch) -> None:
    """Gate risk_off overrides any quadrant => RISK_OFF bands (equity center
    .38 ± .12 -> [0.26, 0.50])."""
    monkeypatch.setattr(
        optimizer_data,
        "load_fund_asset_class",
        _async({fid: _CLASS_OF[fid] for fid in _CLASS_OF}),
    )
    monkeypatch.setattr(
        tb, "fetch_gate_regime", _async(_gate_snapshot(state="risk_off", quadrant="expansion"))
    )
    assets = [FundRefIn(kind="fund", id=fid) for fid in _FUND_IDS]
    labels = [f"fund:{fid}" for fid in _FUND_IDS]
    blocks, regime, _quad = await pb._resolve_regime_block_budgets(
        session=None, datalake=object(), assets=assets, labels=labels  # type: ignore[arg-type]
    )
    assert regime == "RISK_OFF"
    eq = next(b for b in blocks if 0 in b.indices)
    assert abs(eq.lo - 0.26) < 1e-9 and abs(eq.hi - 0.50) < 1e-9


async def test_combo_slowdown_returns_no_blocks(monkeypatch: pytest.MonkeyPatch) -> None:
    """SLOWDOWN routes the goldfix haven (STAG_GOLD sentinel) => no class
    blocks (Task 3 routes the haven)."""
    monkeypatch.setattr(
        optimizer_data,
        "load_fund_asset_class",
        _async({fid: _CLASS_OF[fid] for fid in _CLASS_OF}),
    )
    monkeypatch.setattr(
        tb, "fetch_gate_regime", _async(_gate_snapshot(state="risk_on", quadrant="slowdown"))
    )
    assets = [FundRefIn(kind="fund", id=fid) for fid in _FUND_IDS]
    labels = [f"fund:{fid}" for fid in _FUND_IDS]
    blocks, regime, quad = await pb._resolve_regime_block_budgets(
        session=None, datalake=object(), assets=assets, labels=labels  # type: ignore[arg-type]
    )
    assert regime == "STAG_GOLD"
    assert blocks == []
    assert quad == "slowdown"


async def test_combo_absent_class_and_equity_skipped(monkeypatch: pytest.MonkeyPatch) -> None:
    """A class absent from the universe yields no block; equities (no
    asset_class) are left unbounded (O5) and never fail loud."""
    # Only equity + fixed_income funds present, plus a raw equity stock.
    two_funds = {_FUND_IDS[0]: "equity", _FUND_IDS[1]: "fixed_income"}
    monkeypatch.setattr(optimizer_data, "load_fund_asset_class", _async(two_funds))
    monkeypatch.setattr(tb, "fetch_gate_regime", _async(_gate_snapshot(state="risk_on")))
    assets: list[Any] = [
        FundRefIn(kind="fund", id=_FUND_IDS[0]),
        FundRefIn(kind="fund", id=_FUND_IDS[1]),
        EquityRefIn(kind="equity", ticker="SPY"),
    ]
    labels = [f"fund:{_FUND_IDS[0]}", f"fund:{_FUND_IDS[1]}", "equity:SPY"]
    blocks, regime, _quad = await pb._resolve_regime_block_budgets(
        session=None, datalake=object(), assets=assets, labels=labels  # type: ignore[arg-type]
    )
    assert regime == "RISK_ON"
    # Two blocks only (equity + fixed_income); no alternatives/cash; no equity idx 2.
    classes_covered = sorted(b.indices for b in blocks)
    assert classes_covered == [[0], [1]]


async def test_combo_no_gate_degrades_to_riskon(monkeypatch: pytest.MonkeyPatch) -> None:
    """No gate row (reader returns None) and no datalake => RISK_ON, no quadrant."""
    monkeypatch.setattr(
        optimizer_data,
        "load_fund_asset_class",
        _async({fid: _CLASS_OF[fid] for fid in _CLASS_OF}),
    )
    monkeypatch.setattr(tb, "fetch_gate_regime", _async(None))
    assets = [FundRefIn(kind="fund", id=fid) for fid in _FUND_IDS]
    labels = [f"fund:{fid}" for fid in _FUND_IDS]
    blocks, regime, quad = await pb._resolve_regime_block_budgets(
        session=None, datalake=None, assets=assets, labels=labels  # type: ignore[arg-type]
    )
    assert regime == "RISK_ON"
    assert quad is None
    assert len(blocks) == 4


# ── Task 3: combo dispatch (end-to-end via the optimize route) ────────────────


def _client() -> AsyncClient:
    app = create_app()
    app.dependency_overrides[get_session] = lambda: None
    # The combo gate read is datalake-guarded (None datalake => no gate => RISK_ON
    # in prod). Inject a non-None dummy so the monkeypatched ``fetch_gate_regime``
    # fires and drives the regime/quadrant deterministically.
    app.dependency_overrides[get_optional_datalake_session] = lambda: object()
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


def _stub_returns(monkeypatch: pytest.MonkeyPatch, ids: list[uuid.UUID], n_obs: int = 500) -> None:
    """Aligned returns where the equity fund (idx 0) has the best risk-return so
    an unconstrained min-CVaR concentrates there — making the equity band bind."""

    async def fake_load(
        session: Any,
        assets: list[optimizer_data.AssetRef],
        window_days: int = 730,
        today: dt.date | None = None,
    ) -> pd.DataFrame:
        rng = np.random.default_rng(7)
        index = pd.bdate_range("2024-01-02", periods=n_obs)
        # idx0 equity: high drift, low vol (attractor); others duller.
        drifts = [0.0009, 0.0002, 0.0003, 0.00005]
        vols = [0.006, 0.010, 0.012, 0.002]
        data = {
            ref.label: rng.normal(drifts[i % 4], vols[i % 4], n_obs)
            for i, ref in enumerate(assets)
        }
        return pd.DataFrame(data, index=index)

    monkeypatch.setattr(optimizer_data, "load_aligned_returns", fake_load)


@pytest.fixture(autouse=True)
def _stub_taxonomy(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_class(session: Any, fund_ids: list[uuid.UUID]) -> dict[uuid.UUID, str | None]:
        return {fid: _CLASS_OF.get(fid) for fid in fund_ids}

    async def fake_strategy(session: Any, fund_ids: list[uuid.UUID]) -> dict[uuid.UUID, str | None]:
        return {fid: "Core" for fid in fund_ids}

    monkeypatch.setattr(optimizer_data, "load_fund_asset_class", fake_class)
    monkeypatch.setattr(optimizer_data, "load_fund_strategy_label", fake_strategy)


async def test_combo_respects_riskoff_equity_band(monkeypatch: pytest.MonkeyPatch) -> None:
    """RISK_OFF equity band [0.26, 0.50] is enforced by the combo solve."""
    _stub_returns(monkeypatch, _FUND_IDS)
    monkeypatch.setattr(tb, "fetch_gate_regime", _async(_gate_snapshot(state="risk_off")))
    payload = {
        "assets": [{"kind": "fund", "id": str(fid)} for fid in _FUND_IDS],
        "objective": "combo",
        "constraints": {"cap": 1.0},
    }
    async with _client() as client:
        resp = await client.post("/builder/optimize", json=payload)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["diagnostics"]["combined_regime"] == "RISK_OFF"
    assert body["diagnostics"]["regime_state"] == "risk_off"
    eq_w = next(w["weight"] for w in body["weights"] if w["asset"]["id"] == str(_FUND_IDS[0]))
    assert eq_w <= 0.50 + 1e-6
    assert eq_w >= 0.26 - 1e-6
    # class_bands surfaced for transparency.
    assert body["diagnostics"]["class_bands"]["equity"] == pytest.approx([0.26, 0.50])


async def test_combo_riskon_equity_band_is_floored(monkeypatch: pytest.MonkeyPatch) -> None:
    """Control: RISK_ON raises the equity floor to 0.40 (vs risk_off 0.26)."""
    _stub_returns(monkeypatch, _FUND_IDS)
    monkeypatch.setattr(tb, "fetch_gate_regime", _async(_gate_snapshot(state="risk_on")))
    payload = {
        "assets": [{"kind": "fund", "id": str(fid)} for fid in _FUND_IDS],
        "objective": "combo",
        "constraints": {"cap": 1.0},
    }
    async with _client() as client:
        resp = await client.post("/builder/optimize", json=payload)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["diagnostics"]["combined_regime"] == "RISK_ON"
    eq_w = next(w["weight"] for w in body["weights"] if w["asset"]["id"] == str(_FUND_IDS[0]))
    assert eq_w >= 0.40 - 1e-6
    assert eq_w <= 0.64 + 1e-6


async def test_combo_slowdown_routes_goldfix(monkeypatch: pytest.MonkeyPatch) -> None:
    """SLOWDOWN routes the fixed goldfix haven over available names; equity
    stocks go to 0 and diagnostics.haven_tilt is populated."""
    _stub_returns(monkeypatch, _FUND_IDS)
    monkeypatch.setattr(
        tb, "fetch_gate_regime", _async(_gate_snapshot(state="risk_on", quadrant="slowdown"))
    )
    # Universe: GLD + BIL as equities (haven names) + two ordinary equity stocks.
    payload = {
        "assets": [
            {"kind": "equity", "ticker": "GLD"},
            {"kind": "equity", "ticker": "BIL"},
            {"kind": "equity", "ticker": "AAA"},
            {"kind": "equity", "ticker": "BBB"},
        ],
        "objective": "combo",
        "constraints": {"cap": 1.0},
    }

    async def fake_load(
        session: Any, assets: list[optimizer_data.AssetRef], window_days: int = 730, today: Any = None
    ) -> pd.DataFrame:
        rng = np.random.default_rng(3)
        index = pd.bdate_range("2024-01-02", periods=300)
        return pd.DataFrame(
            {ref.label: rng.normal(0.0003, 0.01, 300) for ref in assets}, index=index
        )

    monkeypatch.setattr(optimizer_data, "load_aligned_returns", fake_load)
    async with _client() as client:
        resp = await client.post("/builder/optimize", json=payload)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["diagnostics"]["combined_regime"] == "STAG_GOLD"
    assert body["diagnostics"]["quadrant"] == "slowdown"
    assert body["diagnostics"]["status"] == "goldfix"
    weights = {w["asset"]["ticker"]: w["weight"] for w in body["weights"]}
    # GLD/BIL present and positive; ordinary stocks zeroed.
    assert weights["GLD"] > 0.0 and weights["BIL"] > 0.0
    assert weights["AAA"] == pytest.approx(0.0, abs=1e-9)
    assert weights["BBB"] == pytest.approx(0.0, abs=1e-9)
    # GLD 0.30 / BIL 0.30 with VOOV/QAI absent -> renormalized to 0.5 / 0.5.
    assert weights["GLD"] == pytest.approx(0.5)
    assert weights["BIL"] == pytest.approx(0.5)
    haven = body["diagnostics"]["haven_tilt"]
    assert haven is not None and set(haven) == {"GLD", "BIL"}
    assert abs(sum(w["weight"] for w in body["weights"]) - 1.0) < 1e-6


async def test_combo_ignores_payload_block_budgets(monkeypatch: pytest.MonkeyPatch) -> None:
    """combo derives bands from the regime; a payload block_budget is IGNORED
    (the equity band is the regime's, not the payload's tight 0.05)."""
    _stub_returns(monkeypatch, _FUND_IDS)
    monkeypatch.setattr(tb, "fetch_gate_regime", _async(_gate_snapshot(state="risk_on")))
    payload = {
        "assets": [{"kind": "fund", "id": str(fid)} for fid in _FUND_IDS],
        "objective": "combo",
        "constraints": {"cap": 1.0, "block_budgets": [{"asset_class": "equity", "hi": 0.05}]},
    }
    async with _client() as client:
        resp = await client.post("/builder/optimize", json=payload)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    eq_w = next(w["weight"] for w in body["weights"] if w["asset"]["id"] == str(_FUND_IDS[0]))
    # If the payload budget had been honoured, eq_w<=0.05; the regime floor 0.40 wins.
    assert eq_w >= 0.40 - 1e-6
