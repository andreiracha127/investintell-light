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

    async def fake_features(
        session: Any, fund_ids: list[uuid.UUID]
    ) -> dict[uuid.UUID, dict[str, float | None]]:
        # 3 planted clusters of 4 funds, well-separated in risk-feature space.
        out: dict[uuid.UUID, dict[str, float | None]] = {}
        for k, fid in enumerate(fund_ids):
            base = float(k // 4) * 10.0  # cluster 0/1/2 centers at 0/10/20
            out[fid] = {
                key: base + 0.1 * (k % 4)
                for key in optimizer_data.RISK_FEATURE_KEYS
            }
        return out

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
    monkeypatch.setattr(optimizer_data, "load_fund_risk_features", fake_features)
    monkeypatch.setattr(optimizer_data, "load_aligned_returns", fake_aligned)
    monkeypatch.setattr(optimizer_data, "load_fund_quality_metrics", fake_quality)
    monkeypatch.setattr(optimizer_data, "load_fund_asset_class", fake_asset_class)
    monkeypatch.setattr(optimizer_data, "load_fund_strategy_label", fake_strategy)
    return ids


def _stub_broad_bl(
    monkeypatch: pytest.MonkeyPatch, n_clusters: int = 4, per_cluster: int = 2
) -> list[uuid.UUID]:
    """Like ``_stub_broad`` but planted with ``n_clusters`` well-separated risk
    clusters and a stubbed ``load_fund_aum`` so the BL equilibrium prior
    (w_mkt → π = δΣw_mkt) can be computed for the selected representatives.

    The shared BL block (``_market_weights_for``) reads AUM via
    ``load_fund_aum`` — which the covariance-only ``_stub_broad`` does not seed —
    so a broad + ``bl_utility`` request needs this extra stub.
    """
    n_funds = n_clusters * per_cluster
    ids = _ids(n_funds)

    async def fake_select(session: Any, filters: Any, **kw: Any) -> list[Any]:
        assert kw.get("max_assets") is None  # broad path removes the cap
        return [
            optimizer_data.UniverseFund(id=i, ticker=f"F{k}", name=f"Fund {k}")
            for k, i in enumerate(ids)
        ]

    async def fake_features(
        session: Any, fund_ids: list[uuid.UUID]
    ) -> dict[uuid.UUID, dict[str, float | None]]:
        out: dict[uuid.UUID, dict[str, float | None]] = {}
        for k, fid in enumerate(fund_ids):
            base = float(k // per_cluster) * 10.0  # well-separated cluster centers
            out[fid] = {
                key: base + 0.1 * (k % per_cluster)
                for key in optimizer_data.RISK_FEATURE_KEYS
            }
        return out

    def _returns_frame(refs: list[Any]) -> pd.DataFrame:
        rng = np.random.default_rng(11)
        return pd.DataFrame(
            {r.label: rng.normal(0.0004, 0.01, 500) for r in refs},
            index=pd.bdate_range("2023-01-02", periods=500),
        )

    async def fake_aligned(
        session: Any, refs: list[Any], window_days: Any = None, today: Any = None
    ) -> pd.DataFrame:
        return _returns_frame(refs)

    # bl_utility is NOT a scenario objective, so the broad path uses the
    # pairwise covariance loader (load_returns_matrix), not the aligned one.
    async def fake_matrix(
        session: Any, refs: list[Any], window_days: Any = None, today: Any = None
    ) -> pd.DataFrame:
        return _returns_frame(refs)

    async def fake_quality(
        session: Any, fund_ids: list[uuid.UUID]
    ) -> dict[uuid.UUID, dict[str, float | None]]:
        return {
            fid: {"sharpe_1y": 0.5 + 0.1 * i, "expense_ratio": 0.005, "aum_usd": 1e8}
            for i, fid in enumerate(fund_ids)
        }

    async def fake_aum(
        session: Any, fund_ids: list[uuid.UUID]
    ) -> dict[uuid.UUID, float | None]:
        # Positive, distinct AUM → a valid (non-degenerate) market-weight prior.
        return {fid: 1e9 * (i + 1) for i, fid in enumerate(fund_ids)}

    async def fake_asset_class(
        session: Any, fund_ids: list[uuid.UUID]
    ) -> dict[uuid.UUID, str | None]:
        return {fid: "equity" for fid in fund_ids}

    async def fake_strategy(
        session: Any, fund_ids: list[uuid.UUID]
    ) -> dict[uuid.UUID, str | None]:
        return {fid: "Large-Cap Growth" for fid in fund_ids}

    monkeypatch.setattr(optimizer_data, "select_universe_funds", fake_select)
    monkeypatch.setattr(optimizer_data, "load_fund_risk_features", fake_features)
    monkeypatch.setattr(optimizer_data, "load_aligned_returns", fake_aligned)
    monkeypatch.setattr(optimizer_data, "load_returns_matrix", fake_matrix)
    monkeypatch.setattr(optimizer_data, "load_fund_quality_metrics", fake_quality)
    monkeypatch.setattr(optimizer_data, "load_fund_aum", fake_aum)
    monkeypatch.setattr(optimizer_data, "load_fund_asset_class", fake_asset_class)
    monkeypatch.setattr(optimizer_data, "load_fund_strategy_label", fake_strategy)
    return ids


async def test_bl_utility_broad_end_to_end(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """bl_utility over a broad universe (NO views) runs end-to-end on the
    equilibrium prior and returns valid weights with mu_equilibrium present.

    Guarantees the Task-1 schema unblock actually flows through the service:
    the broad branch converges to the shared BL block, ``needs_bl`` computes
    ``w_mkt``/``mu_equilibrium``, and ``require_aum`` resolves AUM for the K
    selected representatives. K=4 with the default cap (0.25) is feasible
    (0.25·4 = 1.0), so the effective per-asset cap stays 0.25.
    """
    _stub_broad_bl(monkeypatch, n_clusters=4, per_cluster=2)
    payload = {
        "universe": {"broad_universe": True, "max_positions": 4},
        "objective": "bl_utility",
    }
    async with _client() as client:
        response = await client.post("/builder/optimize", json=payload)

    assert response.status_code == 200, response.text
    body = response.json()

    weights = [w["weight"] for w in body["weights"]]
    assert len(weights) == 4  # one representative per planted cluster
    assert abs(sum(weights) - 1.0) < 1e-6  # fully invested
    assert all(w >= -1e-9 for w in weights)  # long-only
    assert all(w <= 0.25 + 1e-6 for w in weights)  # effective cap respected

    diag = body["diagnostics"]
    assert diag["status"] == "optimal"
    # The equilibrium prior is the heart of the no-views BL path.
    assert diag["mu_equilibrium"] is not None
    assert len(diag["mu_equilibrium"]) == 4
    assert all(isinstance(x, (int, float)) for x in diag["mu_equilibrium"])
    # No views → no posterior re-centering, no view-consistency alarm, and
    # return_ann_bl (μ_posteriorᵀw) is null since there is no posterior.
    assert diag["mu_posterior"] is None
    assert diag["view_consistency"] is None
    assert body["expected"]["return_ann_bl"] is None


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
