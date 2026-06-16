"""End-to-end test for the broad-universe optimize path (Stage 1 + Stage 2).

Data-loading is stubbed at app.optimizer.data; the selection + engine math runs
LIVE so the happy path exercises the real two-stage pipeline.
"""

import uuid
from typing import Any

import numpy as np
import pandas as pd
import pytest
from httpx import ASGITransport, AsyncClient

from app.core.db import get_session
from app.main import create_app
from app.optimizer import data as optimizer_data


def _client() -> AsyncClient:
    app = create_app()
    app.dependency_overrides[get_session] = lambda: None
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


def _ids(n: int) -> list[uuid.UUID]:
    return [uuid.UUID(int=i + 1) for i in range(n)]


def _stub_broad(monkeypatch: pytest.MonkeyPatch, n_funds: int = 12) -> list[uuid.UUID]:
    ids = _ids(n_funds)

    async def fake_select(session: Any, filters: Any, **kw: Any) -> list[Any]:
        assert kw.get("max_assets") is None  # broad path removes the cap
        return [
            optimizer_data.UniverseFund(id=i, ticker=f"F{k}", name=f"Fund {k}")
            for k, i in enumerate(ids)
        ]

    async def fake_matrix(
        session: Any, refs: list[Any], window_days: Any = None, today: Any = None
    ) -> pd.DataFrame:
        # 3 planted clusters of 4 funds, 600 obs, no NaN (all full history).
        rng = np.random.default_rng(5)
        cols = {}
        for c in range(3):
            common = rng.standard_normal((600, 1))
            for j in range(4):
                idio = rng.standard_normal((600, 1))
                ref = refs[c * 4 + j]
                cols[ref.label] = (0.85 * common + 0.15 * idio).ravel()
        return pd.DataFrame(cols, index=pd.bdate_range("2023-01-02", periods=600))

    async def fake_aligned(
        session: Any, refs: list[Any], window_days: Any = None, today: Any = None
    ) -> pd.DataFrame:
        rng = np.random.default_rng(6)
        return pd.DataFrame(
            {r.label: rng.normal(0.0003, 0.009, 500) for r in refs},
            index=pd.bdate_range("2023-01-02", periods=500),
        )

    async def fake_quality(
        session: Any, fund_ids: list[uuid.UUID]
    ) -> dict[uuid.UUID, dict[str, float | None]]:
        return {
            fid: {"sharpe_1y": 0.5 + 0.1 * i, "expense_ratio": 0.005, "aum_usd": 1e8}
            for i, fid in enumerate(fund_ids)
        }

    async def fake_asset_class(
        session: Any, fund_ids: list[uuid.UUID]
    ) -> dict[uuid.UUID, str | None]:
        return {fid: "equity" for fid in fund_ids}

    async def fake_strategy(
        session: Any, fund_ids: list[uuid.UUID]
    ) -> dict[uuid.UUID, str | None]:
        return {fid: "Large-Cap Growth" for fid in fund_ids}

    monkeypatch.setattr(optimizer_data, "select_universe_funds", fake_select)
    monkeypatch.setattr(optimizer_data, "load_returns_matrix", fake_matrix)
    monkeypatch.setattr(optimizer_data, "load_aligned_returns", fake_aligned)
    monkeypatch.setattr(optimizer_data, "load_fund_quality_metrics", fake_quality)
    monkeypatch.setattr(optimizer_data, "load_fund_asset_class", fake_asset_class)
    monkeypatch.setattr(optimizer_data, "load_fund_strategy_label", fake_strategy)
    return ids


async def test_broad_universe_returns_lean_portfolio_with_diagnostics(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _stub_broad(monkeypatch, n_funds=12)
    payload = {
        "universe": {"broad_universe": True, "max_positions": 3, "rank_by": "sharpe_1y"},
        "objective": "min_cvar",
    }
    async with _client() as client:
        response = await client.post("/builder/optimize", json=payload)
    assert response.status_code == 200, response.text
    body = response.json()
    # Lean portfolio: exactly the K selected representatives (one per cluster).
    assert len(body["weights"]) == 3
    weights = [w["weight"] for w in body["weights"]]
    assert abs(sum(weights) - 1.0) < 1e-6
    sel = body["diagnostics"]["selection"]
    assert sel is not None
    assert sel["n_candidates"] == 12
    assert sel["n_selected"] == 3
    assert sel["excluded"] == []
    assert all(w["asset_class"] == "equity" for w in body["weights"])
    assert all(w["strategy_label"] == "Large-Cap Growth" for w in body["weights"])


async def test_broad_universe_too_small_fails_loud(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A universe resolving to <2 funds is a 422 (fail-loud)."""

    async def fake_select(session: Any, filters: Any, **kw: Any) -> list[Any]:
        return [optimizer_data.UniverseFund(id=uuid.UUID(int=1), ticker="F", name="F")]

    monkeypatch.setattr(optimizer_data, "select_universe_funds", fake_select)
    payload = {"universe": {"broad_universe": True}, "objective": "min_cvar"}
    async with _client() as client:
        response = await client.post("/builder/optimize", json=payload)
    assert response.status_code == 422


async def test_broad_universe_explicit_infeasible_cap_fails_loud(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An EXPLICIT cap that can't fill a K-position broad portfolio is a 422.

    K=3 with cap=0.2 → 3×0.2=0.6 < 1, so the lean portfolio cannot be fully
    invested. We refuse to silently raise the user's chosen cap.
    """
    _stub_broad(monkeypatch, n_funds=12)
    payload = {
        "universe": {"broad_universe": True, "max_positions": 3},
        "objective": "min_cvar",
        "constraints": {"cap": 0.2},
    }
    async with _client() as client:
        response = await client.post("/builder/optimize", json=payload)
    assert response.status_code == 422, response.text
    assert "cap" in response.text or "infeasible" in response.text
    assert "increase max_positions" in response.text


async def test_broad_universe_explicit_feasible_cap_is_respected(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An EXPLICIT feasible cap is honored, never overridden.

    K=3 with cap=0.5 → 3×0.5=1.5 ≥ 1, so the cap is feasible and must bind.
    """
    _stub_broad(monkeypatch, n_funds=12)
    payload = {
        "universe": {"broad_universe": True, "max_positions": 3},
        "objective": "min_cvar",
        "constraints": {"cap": 0.5},
    }
    async with _client() as client:
        response = await client.post("/builder/optimize", json=payload)
    assert response.status_code == 200, response.text
    body = response.json()
    assert all(w["weight"] <= 0.5 + 1e-6 for w in body["weights"])


async def test_broad_universe_over_ceiling_is_422_not_500(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A universe exceeding MAX_UNIVERSE_CANDIDATES is a fail-loud 422, not a raw
    500 (a 500 also strips the CORS headers, surfacing as a misleading CORS error
    in the browser)."""

    async def fake_select(session: Any, filters: Any, **kw: Any) -> list[Any]:
        raise ValueError(
            "universe matched more than 2000 funds — narrow the filters"
        )

    monkeypatch.setattr(optimizer_data, "select_universe_funds", fake_select)
    payload = {"universe": {"broad_universe": True}, "objective": "min_cvar"}
    async with _client() as client:
        response = await client.post("/builder/optimize", json=payload)
    assert response.status_code == 422, response.text
    assert "more than 2000" in response.text
