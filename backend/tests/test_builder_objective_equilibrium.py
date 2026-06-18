"""Onda 0 - max_return_cvar solves off the BL equilibrium when no views exist."""

import numpy as np
import pandas as pd
import pytest

from app.optimizer import data as optimizer_data
from app.optimizer import engine
from app.schemas.builder import OptimizeRequest
from app.services import portfolio_builder as pb

_IDS = [f"00000000-0000-0000-0000-00000000000{i}" for i in range(1, 4)]


async def test_max_return_cvar_without_views_uses_equilibrium(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    n_obs = 500
    index = pd.bdate_range("2024-01-02", periods=n_obs)
    rng = np.random.default_rng(7)

    async def fake_load(session, assets, window_days=None, today=None):
        return pd.DataFrame(
            {ref.label: rng.normal(0.0004, 0.01, n_obs) for ref in assets},
            index=index,
        )

    async def fake_aum(session, fund_ids):
        return {fid: 1e9 * (i + 1) for i, fid in enumerate(fund_ids)}

    async def fake_class(session, fund_ids):
        return {fid: "equity" for fid in fund_ids}

    async def fake_strategy(session, fund_ids):
        return {fid: "Core" for fid in fund_ids}

    captured: dict[str, object] = {}

    def fake_solver(
        scenarios,
        *,
        mu,
        cvar_limit,
        cap=None,
        min_weight=None,
        bounds=None,
        alpha=0.95,
        cvar_tol=1e-4,
    ):
        captured["mu"] = mu
        w = np.full(scenarios.shape[1], 1.0 / scenarios.shape[1])
        return w, "optimal"

    monkeypatch.setattr(optimizer_data, "load_aligned_returns", fake_load)
    monkeypatch.setattr(optimizer_data, "load_fund_aum", fake_aum)
    monkeypatch.setattr(optimizer_data, "load_fund_asset_class", fake_class)
    monkeypatch.setattr(optimizer_data, "load_fund_strategy_label", fake_strategy)
    monkeypatch.setattr(engine, "solve_max_return_cvar_capped", fake_solver)

    payload = OptimizeRequest(
        assets=[{"kind": "fund", "id": i} for i in _IDS],
        objective="max_return_cvar",
        cvar_limit=0.02,
    )  # NO views
    result = await pb.run_optimize(session=None, payload=payload)  # type: ignore[arg-type]

    mu = np.asarray(captured["mu"])
    assert mu.shape == (3,)
    assert np.isfinite(mu).all()
    assert result.diagnostics.status == "optimal"
