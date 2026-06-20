"""Tests for the per-equity look-through overlap cap (Sprint B / Task 4).

When ``constraints.overlap_cap`` is set, ``run_optimize`` adds a HARD linear
constraint per equity security ``s``: ``Σ_i h_{fund_i,s}·w_i ≤ overlap_cap``,
limiting aggregate indirect exposure to any single stock held across funds.

The optimizer/BL math runs LIVE (real cvxpy solve); only the data loaders and
``lookthrough_exposure.fund_equity_exposure`` are stubbed — the same seam the
other builder suites use (``test_builder_route.py`` /
``test_builder_broad_universe.py``).
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
from app.services import portfolio_builder

# Three funds; F0 and F1 both hold stock X (30% and 40% look-through), F2 holds
# a different stock Y. With overlap_cap=0.10 the combined exposure to X must be
# clamped; without it the unconstrained optimizer pours weight into F0/F1.
_FUND_IDS = [uuid.UUID(f"00000000-0000-0000-0000-00000000000{i}") for i in range(1, 4)]
_STOCK_X = "STOCKX0000"
_STOCK_Y = "STOCKY0000"


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
        return {fid: "equity" for fid in fund_ids}

    async def fake_strategy(
        session: Any, fund_ids: list[uuid.UUID]
    ) -> dict[uuid.UUID, str | None]:
        return {fid: "Core" for fid in fund_ids}

    monkeypatch.setattr(optimizer_data, "load_fund_asset_class", fake_class)
    monkeypatch.setattr(optimizer_data, "load_fund_strategy_label", fake_strategy)


def _stub_returns(monkeypatch: pytest.MonkeyPatch, n_obs: int = 500) -> None:
    """Aligned returns where F0/F1 (which hold X) have the BEST risk-return, so an
    unconstrained min_cvar wants to concentrate there — making the overlap cap
    actually bind. Deterministic via a fixed seed."""

    async def fake_load(
        session: Any,
        assets: list[optimizer_data.AssetRef],
        window_days: int = 730,
        today: dt.date | None = None,
    ) -> pd.DataFrame:
        rng = np.random.default_rng(7)
        index = pd.bdate_range("2024-01-02", periods=n_obs)
        # F0, F1 low-vol/positive drift; F2 high-vol → min_cvar favors F0/F1.
        vols = [0.006, 0.006, 0.020]
        drifts = [0.0006, 0.0006, 0.0001]
        data = {
            ref.label: rng.normal(drifts[i], vols[i], n_obs)
            for i, ref in enumerate(assets)
        }
        return pd.DataFrame(data, index=index)

    monkeypatch.setattr(optimizer_data, "load_aligned_returns", fake_load)


def _stub_exposure(
    monkeypatch: pytest.MonkeyPatch,
    exposure: dict[uuid.UUID, dict[str, float]],
) -> None:
    async def fake_exposure(
        session: Any, datalake: Any, fund_instrument_ids: list[uuid.UUID]
    ) -> dict[uuid.UUID, dict[str, float]]:
        return {fid: exposure[fid] for fid in fund_instrument_ids if fid in exposure}

    monkeypatch.setattr(
        portfolio_builder.lookthrough_exposure,
        "fund_equity_exposure",
        fake_exposure,
    )


def _x_exposure(
    weights: list[dict[str, Any]], holdings: dict[uuid.UUID, float]
) -> float:
    """Aggregate look-through exposure to stock X = Σ w_fund · h_fund,X."""
    by_id = {w["asset"]["id"]: float(w["weight"]) for w in weights}
    return sum(by_id[str(fid)] * frac for fid, frac in holdings.items())


async def test_overlap_cap_clamps_aggregate_equity_exposure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """With overlap_cap=0.10, aggregate look-through exposure to X is ≤ cap."""
    _stub_returns(monkeypatch)
    holdings_x = {_FUND_IDS[0]: 0.30, _FUND_IDS[1]: 0.40}
    _stub_exposure(
        monkeypatch,
        {
            _FUND_IDS[0]: {_STOCK_X: 0.30},
            _FUND_IDS[1]: {_STOCK_X: 0.40},
            _FUND_IDS[2]: {_STOCK_Y: 0.05},
        },
    )
    payload = {
        "assets": [_fund_ref(i) for i in range(3)],
        "objective": "min_cvar",
        "constraints": {"cap": 1.0, "overlap_cap": 0.10},
    }
    async with _client() as client:
        response = await client.post("/builder/optimize", json=payload)
    assert response.status_code == 200, response.text
    body = response.json()
    weights = body["weights"]
    assert abs(sum(w["weight"] for w in weights) - 1.0) < 1e-6
    exposure_x = _x_exposure(weights, holdings_x)
    assert exposure_x <= 0.10 + 1e-6, f"X exposure {exposure_x} exceeds cap"


async def test_without_overlap_cap_exposure_exceeds_threshold(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Control: WITHOUT overlap_cap the same setup blows past 0.10 exposure to X."""
    _stub_returns(monkeypatch)
    holdings_x = {_FUND_IDS[0]: 0.30, _FUND_IDS[1]: 0.40}
    # Exposure stub is present but should never be consulted when overlap_cap is
    # unset — the constraint block is skipped entirely.
    _stub_exposure(
        monkeypatch,
        {
            _FUND_IDS[0]: {_STOCK_X: 0.30},
            _FUND_IDS[1]: {_STOCK_X: 0.40},
            _FUND_IDS[2]: {_STOCK_Y: 0.05},
        },
    )
    payload = {
        "assets": [_fund_ref(i) for i in range(3)],
        "objective": "min_cvar",
        "constraints": {"cap": 1.0},
    }
    async with _client() as client:
        response = await client.post("/builder/optimize", json=payload)
    assert response.status_code == 200, response.text
    body = response.json()
    exposure_x = _x_exposure(body["weights"], holdings_x)
    assert exposure_x > 0.10, f"control X exposure {exposure_x} should exceed 0.10"


async def test_overlap_cap_no_security_over_threshold_is_noop(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When no security's MAX per-fund exposure exceeds the cap, the pruning
    rule generates ZERO LinearConstraints (no-op): the solve proceeds exactly as
    if no overlap_cap were set. We assert by spying on the engine solver to make
    sure ``linear`` is empty/None for every qualifying security."""
    _stub_returns(monkeypatch)
    # Every per-fund exposure (0.05 / 0.08) is below the 0.10 cap → no constraint
    # can ever bind (Σ w·h ≤ max_i h_i ≤ 0.10), so none should be generated.
    _stub_exposure(
        monkeypatch,
        {
            _FUND_IDS[0]: {_STOCK_X: 0.05},
            _FUND_IDS[1]: {_STOCK_X: 0.08},
            _FUND_IDS[2]: {_STOCK_Y: 0.05},
        },
    )

    captured: dict[str, Any] = {}
    real_solve = portfolio_builder.engine.solve_min_cvar

    def spy_solve(*args: Any, **kwargs: Any) -> Any:
        captured["linear"] = kwargs.get("linear")
        return real_solve(*args, **kwargs)

    monkeypatch.setattr(portfolio_builder.engine, "solve_min_cvar", spy_solve)

    payload = {
        "assets": [_fund_ref(i) for i in range(3)],
        "objective": "min_cvar",
        "constraints": {"cap": 1.0, "overlap_cap": 0.10},
    }
    async with _client() as client:
        response = await client.post("/builder/optimize", json=payload)
    assert response.status_code == 200, response.text
    # No security qualified → no LinearConstraint passed to the solver.
    assert not captured["linear"]


async def test_overlap_cap_validation_rejects_out_of_range() -> None:
    """overlap_cap must be in (0, 1]; 0 and >1 are 422 (schema validation)."""
    for bad in (0.0, 1.5, -0.1):
        payload = {
            "assets": [_fund_ref(i) for i in range(3)],
            "objective": "min_cvar",
            "constraints": {"overlap_cap": bad},
        }
        async with _client() as client:
            response = await client.post("/builder/optimize", json=payload)
        assert response.status_code == 422, (bad, response.text)
