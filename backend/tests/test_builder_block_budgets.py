"""Tests for per-asset-class block budgets across ALL solver paths (Sprint B /
Task 7b, closing the spec §5.1 gap).

Sprint B Task 1 made every engine solver ACCEPT a ``blocks`` kwarg, but the
orchestrator only wired it into ``min_cvar`` / ``max_return_cvar`` (via
``BoundsBundle``). Task 7b passes ``blocks`` to the mu-free solvers
(``equal_weight`` / ``min_vol`` / ``erc`` / ``max_diversification``) and to
``bl_utility`` too, so a requested asset-class budget is honoured regardless of
objective.

The optimizer runs LIVE (real cvxpy solve); only the data loaders are stubbed —
the same seam ``test_builder_overlap.py`` uses. The asset-class loader
(``load_fund_asset_class``) is what ``_resolve_block_budgets`` consults to map
each fund onto a block, so it returns DISTINCT classes here.
"""

import datetime as dt
import uuid
from typing import Any

import numpy as np
import pandas as pd
import pytest
from httpx import ASGITransport, AsyncClient

from app.core.db import get_session
from app.main import create_app
from app.optimizer import data as optimizer_data

# Three funds: F0 and F1 are EQUITY (best risk-return → an unconstrained min_vol
# / erc wants to concentrate there), F2 is FIXED_INCOME. With a block budget of
# equity ≤ 0.40 the combined equity weight (F0 + F1) must be clamped.
_FUND_IDS = [uuid.UUID(f"00000000-0000-0000-0000-00000000000{i}") for i in range(1, 4)]
_CLASS_OF = {_FUND_IDS[0]: "equity", _FUND_IDS[1]: "equity", _FUND_IDS[2]: "fixed_income"}


def _client() -> AsyncClient:
    app = create_app()
    app.dependency_overrides[get_session] = lambda: None
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


def _fund_ref(i: int) -> dict[str, str]:
    return {"kind": "fund", "id": str(_FUND_IDS[i])}


@pytest.fixture(autouse=True)
def _stub_result_taxonomy(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_class(
        session: Any, fund_ids: list[uuid.UUID]
    ) -> dict[uuid.UUID, str | None]:
        return {fid: _CLASS_OF[fid] for fid in fund_ids}

    async def fake_strategy(
        session: Any, fund_ids: list[uuid.UUID]
    ) -> dict[uuid.UUID, str | None]:
        return {fid: "Core" for fid in fund_ids}

    monkeypatch.setattr(optimizer_data, "load_fund_asset_class", fake_class)
    monkeypatch.setattr(optimizer_data, "load_fund_strategy_label", fake_strategy)


def _stub_returns(monkeypatch: pytest.MonkeyPatch, n_obs: int = 500) -> None:
    """Aligned returns where the two EQUITY funds (F0/F1) have the best
    risk-return, so an unconstrained min_vol/erc concentrates there — making an
    equity block budget actually bind. Deterministic via a fixed seed."""

    async def fake_load(
        session: Any,
        assets: list[optimizer_data.AssetRef],
        window_days: int = 730,
        today: dt.date | None = None,
    ) -> pd.DataFrame:
        rng = np.random.default_rng(11)
        index = pd.bdate_range("2024-01-02", periods=n_obs)
        # F0, F1 (equity) low-vol; F2 (fixed_income) high-vol → min_vol/erc favor
        # the equity pair absent a budget.
        vols = [0.005, 0.005, 0.020]
        drifts = [0.0006, 0.0006, 0.0001]
        data = {
            ref.label: rng.normal(drifts[i], vols[i], n_obs)
            for i, ref in enumerate(assets)
        }
        return pd.DataFrame(data, index=index)

    monkeypatch.setattr(optimizer_data, "load_aligned_returns", fake_load)


def _equity_weight(weights: list[dict[str, Any]]) -> float:
    """Sum of weights for funds whose resolved asset_class is equity."""
    equity_ids = {str(fid) for fid, cls in _CLASS_OF.items() if cls == "equity"}
    return sum(float(w["weight"]) for w in weights if w["asset"]["id"] in equity_ids)


@pytest.mark.parametrize("objective", ["min_vol", "erc", "max_diversification"])
async def test_block_budget_clamps_equity_weight_mu_free(
    monkeypatch: pytest.MonkeyPatch, objective: str
) -> None:
    """With equity ≤ 0.40 the summed equity weight is clamped for the mu-free
    objectives that previously ignored block budgets (the Task 7b fix)."""
    _stub_returns(monkeypatch)
    payload = {
        "assets": [_fund_ref(i) for i in range(3)],
        "objective": objective,
        "constraints": {
            "cap": 1.0,
            "block_budgets": [{"asset_class": "equity", "hi": 0.40}],
        },
    }
    async with _client() as client:
        response = await client.post("/builder/optimize", json=payload)
    assert response.status_code == 200, response.text
    weights = response.json()["weights"]
    assert abs(sum(w["weight"] for w in weights) - 1.0) < 1e-6
    equity_w = _equity_weight(weights)
    assert equity_w <= 0.40 + 1e-6, f"{objective}: equity weight {equity_w} exceeds 0.40"


async def test_without_block_budget_equity_weight_exceeds_threshold(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Control: WITHOUT a block budget, min_vol concentrates in the equity pair
    well past 0.40, proving the budget (above) is what clamps it."""
    _stub_returns(monkeypatch)
    payload = {
        "assets": [_fund_ref(i) for i in range(3)],
        "objective": "min_vol",
        "constraints": {"cap": 1.0},
    }
    async with _client() as client:
        response = await client.post("/builder/optimize", json=payload)
    assert response.status_code == 200, response.text
    equity_w = _equity_weight(response.json()["weights"])
    assert equity_w > 0.40, f"control equity weight {equity_w} should exceed 0.40"
