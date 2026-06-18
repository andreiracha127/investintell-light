"""T2C-7/T2C-8 — regime-conditional CVaR limit multiplier."""

import pytest

from app.services import portfolio_builder as pb


def test_multiplier_risk_off_tightens_limit() -> None:
    assert pb.regime_cvar_multiplier("risk_off", risk_off_factor=0.5) == 0.5


def test_multiplier_risk_on_is_neutral() -> None:
    assert pb.regime_cvar_multiplier("risk_on", risk_off_factor=0.5) == 1.0


def test_multiplier_unknown_state_is_neutral() -> None:
    assert pb.regime_cvar_multiplier(None, risk_off_factor=0.5) == 1.0
    assert pb.regime_cvar_multiplier("something_else", risk_off_factor=0.5) == 1.0


def test_multiplier_rejects_nonpositive_factor() -> None:
    with pytest.raises(ValueError, match="risk_off_factor"):
        pb.regime_cvar_multiplier("risk_off", risk_off_factor=0.0)


def test_apply_regime_to_limit_tightens() -> None:
    assert pb.apply_regime_cvar_limit(0.10, "risk_off", risk_off_factor=0.5) == pytest.approx(0.05)
    assert pb.apply_regime_cvar_limit(0.10, "risk_on", risk_off_factor=0.5) == pytest.approx(0.10)


async def test_run_optimize_risk_off_halves_the_cvar_limit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """With _OVERRIDE_REGIME_STATE='risk_off', the max_return_cvar branch must
    pass cvar_limit * 0.5 to the engine solver."""
    import numpy as np
    import pandas as pd

    from app.optimizer import data as optimizer_data
    from app.optimizer import engine
    from app.schemas.builder import OptimizeRequest

    n_obs = 500
    index = pd.bdate_range("2024-01-02", periods=n_obs)
    rng = np.random.default_rng(5)

    async def fake_load(session, assets, window_days=None, today=None):
        return pd.DataFrame(
            {ref.label: rng.normal(0.0003, 0.01, n_obs) for ref in assets}, index=index
        )

    async def fake_aum(session, fund_ids):
        return {fid: 1e9 * (i + 1) for i, fid in enumerate(fund_ids)}

    async def fake_class(session, fund_ids):
        return {fid: "equity" for fid in fund_ids}

    async def fake_strategy(session, fund_ids):
        return {fid: "Core" for fid in fund_ids}

    captured: dict[str, float] = {}

    def fake_solver(scenarios, *, mu, cvar_limit, cap=None, min_weight=None,
                    bounds=None, alpha=0.95, cvar_tol=1e-4):
        captured["cvar_limit"] = cvar_limit
        w = np.full(scenarios.shape[1], 1.0 / scenarios.shape[1])
        return w, "optimal"

    monkeypatch.setattr(optimizer_data, "load_aligned_returns", fake_load)
    monkeypatch.setattr(optimizer_data, "load_fund_aum", fake_aum)
    monkeypatch.setattr(optimizer_data, "load_fund_asset_class", fake_class)
    monkeypatch.setattr(optimizer_data, "load_fund_strategy_label", fake_strategy)
    monkeypatch.setattr(engine, "solve_max_return_cvar_capped", fake_solver)
    monkeypatch.setattr(pb, "_OVERRIDE_REGIME_STATE", "risk_off", raising=False)

    payload = OptimizeRequest(
        assets=[
            {"kind": "fund", "id": f"00000000-0000-0000-0000-00000000000{i}"}
            for i in range(1, 5)
        ],
        objective="max_return_cvar",
        cvar_limit=0.20,
        views=[
            {
                "type": "absolute",
                "asset": {
                    "kind": "fund",
                    "id": "00000000-0000-0000-0000-000000000001",
                },
                "q": 0.15,
                "confidence": 0.6,
            }
        ],
    )
    await pb.run_optimize(session=None, payload=payload)  # type: ignore[arg-type]
    assert captured["cvar_limit"] == pytest.approx(0.10)  # 0.20 * 0.5
    monkeypatch.setattr(pb, "_OVERRIDE_REGIME_STATE", None, raising=False)


async def test_run_optimize_exposes_effective_cvar_and_regime(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """risk_off halves the ceiling and diagnostics expose the applied values."""
    import numpy as np
    import pandas as pd

    from app.optimizer import data as optimizer_data
    from app.optimizer import engine
    from app.schemas.builder import OptimizeRequest

    n_obs = 500
    index = pd.bdate_range("2024-01-02", periods=n_obs)
    rng = np.random.default_rng(11)
    ids = [f"00000000-0000-0000-0000-00000000000{i}" for i in range(1, 4)]

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
        w = np.full(scenarios.shape[1], 1.0 / scenarios.shape[1])
        return w, "optimal"

    monkeypatch.setattr(optimizer_data, "load_aligned_returns", fake_load)
    monkeypatch.setattr(optimizer_data, "load_fund_aum", fake_aum)
    monkeypatch.setattr(optimizer_data, "load_fund_asset_class", fake_class)
    monkeypatch.setattr(optimizer_data, "load_fund_strategy_label", fake_strategy)
    monkeypatch.setattr(engine, "solve_max_return_cvar_capped", fake_solver)
    monkeypatch.setattr(pb, "_OVERRIDE_REGIME_STATE", "risk_off", raising=False)

    payload = OptimizeRequest(
        assets=[{"kind": "fund", "id": i} for i in ids],
        objective="max_return_cvar",
        cvar_limit=0.20,
    )
    result = await pb.run_optimize(session=None, payload=payload)  # type: ignore[arg-type]
    assert result.diagnostics.cvar_limit_effective == pytest.approx(0.10)
    assert result.diagnostics.regime_state == "risk_off"
    monkeypatch.setattr(pb, "_OVERRIDE_REGIME_STATE", None, raising=False)
