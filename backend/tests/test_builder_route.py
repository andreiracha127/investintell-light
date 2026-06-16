"""Tests for POST /builder/optimize (app/api/routes/builder.py).

The data-loading layer is stubbed at its canonical module
(``app.optimizer.data``) — no live DB. The optimizer/BL math stays LIVE so
the happy paths exercise the real pipeline end to end.

422 contract covered: insufficient common history, unknown asset, views with
equities / funds without AUM, rank-deficient P.
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

_FUND_IDS = [uuid.UUID(f"00000000-0000-0000-0000-00000000000{i}") for i in range(1, 6)]


def _client() -> AsyncClient:
    app = create_app()
    app.dependency_overrides[get_session] = lambda: None
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


@pytest.fixture(autouse=True)
def _stub_result_taxonomy(monkeypatch: pytest.MonkeyPatch) -> None:
    """Default stubs for the result-taxonomy loaders the response path calls
    unconditionally (asset_class + strategy_label). The DB session is None in
    this suite, so the real loaders cannot run; tests needing a specific
    asset_class (block budgets) override via ``_stub_asset_class`` afterwards."""

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


def _fund_ref(i: int) -> dict[str, str]:
    return {"kind": "fund", "id": str(_FUND_IDS[i])}


def _stub_returns(monkeypatch: pytest.MonkeyPatch, n_obs: int = 500) -> None:
    async def fake_load(
        session: Any,
        assets: list[optimizer_data.AssetRef],
        window_days: int = 730,
        today: dt.date | None = None,
    ) -> pd.DataFrame:
        rng = np.random.default_rng(11)
        index = pd.bdate_range("2024-01-02", periods=n_obs)
        data = {
            ref.label: rng.normal(0.0003, 0.008 + 0.002 * i, n_obs)
            for i, ref in enumerate(assets)
        }
        return pd.DataFrame(data, index=index)

    monkeypatch.setattr(optimizer_data, "load_aligned_returns", fake_load)


def _stub_aum(
    monkeypatch: pytest.MonkeyPatch, aum: dict[uuid.UUID, float | None] | None = None
) -> None:
    async def fake_aum(
        session: Any, fund_ids: list[uuid.UUID]
    ) -> dict[uuid.UUID, float | None]:
        if aum is not None:
            return {fund_id: aum.get(fund_id) for fund_id in fund_ids}
        return {fund_id: 1e9 * (i + 1) for i, fund_id in enumerate(fund_ids)}

    monkeypatch.setattr(optimizer_data, "load_fund_aum", fake_aum)


def _stub_asset_class(
    monkeypatch: pytest.MonkeyPatch,
    classes: dict[uuid.UUID, str | None] | None = None,
) -> None:
    async def fake_class(
        session: Any, fund_ids: list[uuid.UUID]
    ) -> dict[uuid.UUID, str | None]:
        if classes is not None:
            return {fund_id: classes.get(fund_id) for fund_id in fund_ids}
        # Default: alternate equity / fixed_income so blocks have ≥1 member.
        order = ("equity", "fixed_income")
        return {fid: order[i % 2] for i, fid in enumerate(fund_ids)}

    monkeypatch.setattr(optimizer_data, "load_fund_asset_class", fake_class)


async def test_optimize_min_cvar_no_views_happy_path(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _stub_returns(monkeypatch)
    payload = {
        "assets": [_fund_ref(i) for i in range(4)],
        "objective": "min_cvar",
    }
    async with _client() as client:
        response = await client.post("/builder/optimize", json=payload)
    assert response.status_code == 200, response.text
    body = response.json()
    weights = [w["weight"] for w in body["weights"]]
    assert abs(sum(weights) - 1.0) < 1e-6
    assert all(-1e-9 <= w <= 0.25 + 1e-6 for w in weights)  # default cap
    assert body["diagnostics"]["status"] == "optimal"
    assert body["diagnostics"]["n_obs"] == 500
    assert body["diagnostics"]["mu_posterior"] is None
    assert body["expected"]["return_ann_bl"] is None
    assert body["expected"]["vol_ann"] > 0
    assert body["expected"]["cvar_95_in_sample"] > 0


async def test_optimize_with_absolute_view_returns_bl_diagnostics(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _stub_returns(monkeypatch)
    _stub_aum(monkeypatch)
    payload = {
        "assets": [_fund_ref(i) for i in range(4)],
        "objective": "min_cvar",
        "constraints": {"cap": 0.5},
        "views": [
            {"type": "absolute", "asset": _fund_ref(0), "q": 0.12, "confidence": 0.5}
        ],
    }
    async with _client() as client:
        response = await client.post("/builder/optimize", json=payload)
    assert response.status_code == 200, response.text
    body = response.json()
    assert abs(sum(w["weight"] for w in body["weights"]) - 1.0) < 1e-6
    assert body["diagnostics"]["mu_equilibrium"] is not None
    assert body["diagnostics"]["mu_posterior"] is not None
    assert body["expected"]["return_ann_bl"] is not None
    # The bullish view must raise the posterior μ of the viewed asset.
    assert (
        body["diagnostics"]["mu_posterior"][0] > body["diagnostics"]["mu_equilibrium"][0]
    )


async def test_optimize_bl_utility_without_views(monkeypatch: pytest.MonkeyPatch) -> None:
    _stub_returns(monkeypatch)
    _stub_aum(monkeypatch)
    payload = {
        "assets": [_fund_ref(i) for i in range(4)],
        "objective": "bl_utility",
        "constraints": {"cap": None},
    }
    async with _client() as client:
        response = await client.post("/builder/optimize", json=payload)
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["diagnostics"]["mu_equilibrium"] is not None
    assert body["diagnostics"]["mu_posterior"] is None


async def test_insufficient_history_maps_to_422(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_load(session: Any, assets: Any, **kwargs: Any) -> pd.DataFrame:
        raise ValueError(
            "insufficient common history: 120 overlapping observations across the 2 assets"
        )

    monkeypatch.setattr(optimizer_data, "load_aligned_returns", fake_load)
    payload = {"assets": [_fund_ref(0), _fund_ref(1)], "constraints": {"cap": 0.6}}
    async with _client() as client:
        response = await client.post("/builder/optimize", json=payload)
    assert response.status_code == 422
    assert "insufficient common history" in response.json()["detail"]


async def test_unknown_asset_maps_to_422(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_load(session: Any, assets: Any, **kwargs: Any) -> pd.DataFrame:
        raise ValueError(f"unknown asset or no NAV history in window: fund:{_FUND_IDS[0]}")

    monkeypatch.setattr(optimizer_data, "load_aligned_returns", fake_load)
    payload = {"assets": [_fund_ref(0), _fund_ref(1)], "constraints": {"cap": 0.6}}
    async with _client() as client:
        response = await client.post("/builder/optimize", json=payload)
    assert response.status_code == 422
    assert "unknown asset" in response.json()["detail"]


async def test_views_with_equity_universe_maps_to_422(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _stub_returns(monkeypatch)
    payload = {
        "assets": [_fund_ref(0), _fund_ref(1), {"kind": "equity", "ticker": "AAPL"}],
        "constraints": {"cap": 0.5},
        "views": [
            {"type": "absolute", "asset": _fund_ref(0), "q": 0.10, "confidence": 0.5}
        ],
    }
    async with _client() as client:
        response = await client.post("/builder/optimize", json=payload)
    assert response.status_code == 422
    detail = response.json()["detail"]
    assert "equities" in detail and "equity:AAPL" in detail


async def test_views_with_missing_fund_aum_maps_to_422(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _stub_returns(monkeypatch)
    _stub_aum(monkeypatch, aum={_FUND_IDS[0]: 5e9, _FUND_IDS[1]: None})
    payload = {
        "assets": [_fund_ref(0), _fund_ref(1)],
        "constraints": {"cap": 0.6},
        "views": [
            {"type": "absolute", "asset": _fund_ref(0), "q": 0.10, "confidence": 0.5}
        ],
    }
    async with _client() as client:
        response = await client.post("/builder/optimize", json=payload)
    assert response.status_code == 422
    detail = response.json()["detail"]
    assert "AUM" in detail and str(_FUND_IDS[1]) in detail


async def test_rank_deficient_views_map_to_422(monkeypatch: pytest.MonkeyPatch) -> None:
    _stub_returns(monkeypatch)
    _stub_aum(monkeypatch)
    payload = {
        "assets": [_fund_ref(i) for i in range(3)],
        "constraints": {"cap": 0.5},
        "views": [
            {"type": "absolute", "asset": _fund_ref(0), "q": 0.10, "confidence": 0.5},
            {"type": "absolute", "asset": _fund_ref(0), "q": 0.12, "confidence": 0.5},
        ],
    }
    async with _client() as client:
        response = await client.post("/builder/optimize", json=payload)
    assert response.status_code == 422
    assert "linearmente dependentes" in response.json()["detail"]


async def test_view_on_asset_outside_universe_maps_to_422(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _stub_returns(monkeypatch)
    _stub_aum(monkeypatch)
    payload = {
        "assets": [_fund_ref(0), _fund_ref(1)],
        "constraints": {"cap": 0.6},
        "views": [
            {"type": "absolute", "asset": _fund_ref(4), "q": 0.10, "confidence": 0.5}
        ],
    }
    async with _client() as client:
        response = await client.post("/builder/optimize", json=payload)
    assert response.status_code == 422
    assert "not in the request universe" in response.json()["detail"]


# ── Block budgets (per-asset-class Σ-weight bounds, min_cvar only) ───────────


async def test_block_budget_binds_min_cvar(monkeypatch: pytest.MonkeyPatch) -> None:
    _stub_returns(monkeypatch)
    # Funds 0 & 2 are equity; cap the equity block at 30% — it must bind.
    _stub_asset_class(
        monkeypatch,
        classes={
            _FUND_IDS[0]: "equity",
            _FUND_IDS[1]: "fixed_income",
            _FUND_IDS[2]: "equity",
            _FUND_IDS[3]: "fixed_income",
        },
    )
    payload = {
        "assets": [_fund_ref(i) for i in range(4)],
        "objective": "min_cvar",
        "constraints": {
            "cap": 0.5,
            "block_budgets": [{"asset_class": "equity", "lo": 0.0, "hi": 0.3}],
        },
    }
    async with _client() as client:
        response = await client.post("/builder/optimize", json=payload)
    assert response.status_code == 200, response.text
    body = response.json()
    by_id = {w["asset"]["id"]: w["weight"] for w in body["weights"]}
    equity_sum = by_id[str(_FUND_IDS[0])] + by_id[str(_FUND_IDS[2])]
    assert equity_sum <= 0.3 + 1e-6
    assert abs(sum(w["weight"] for w in body["weights"]) - 1.0) < 1e-6


async def test_block_budget_does_not_drop_default_cap(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Regression: supplying block_budgets must NOT silently drop the scalar
    per-asset cap. With the DEFAULT cap (0.25) left untouched, the bundle path
    used to translate to cap_vec=None and let a single fund take up to its
    block hi (or 1.0). Assert the 25% per-asset cap still binds every weight."""
    _stub_returns(monkeypatch)
    _stub_asset_class(
        monkeypatch,
        classes={
            _FUND_IDS[0]: "equity",
            _FUND_IDS[1]: "fixed_income",
            _FUND_IDS[2]: "equity",
            _FUND_IDS[3]: "fixed_income",
        },
    )
    payload = {
        "assets": [_fund_ref(i) for i in range(4)],
        "objective": "min_cvar",
        # cap omitted → default 0.25; a wide block budget that does NOT itself
        # cap any single asset below 0.25, so only the scalar cap can bind.
        "constraints": {
            "block_budgets": [{"asset_class": "fixed_income", "lo": 0.0, "hi": 0.9}],
        },
    }
    async with _client() as client:
        response = await client.post("/builder/optimize", json=payload)
    assert response.status_code == 200, response.text
    body = response.json()
    weights = [w["weight"] for w in body["weights"]]
    # The default 25% per-asset cap must still bind despite block_budgets.
    assert all(w <= 0.25 + 1e-6 for w in weights), weights
    assert abs(sum(weights) - 1.0) < 1e-6


async def test_block_budget_with_views_binds_min_cvar(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The reachable combination flagged in review: min_cvar + views +
    block_budgets must still honour the block bound (not silently drop it)."""
    _stub_returns(monkeypatch)
    _stub_aum(monkeypatch)
    _stub_asset_class(
        monkeypatch,
        classes={
            _FUND_IDS[0]: "equity",
            _FUND_IDS[1]: "fixed_income",
            _FUND_IDS[2]: "equity",
            _FUND_IDS[3]: "fixed_income",
        },
    )
    payload = {
        "assets": [_fund_ref(i) for i in range(4)],
        "objective": "min_cvar",
        "constraints": {
            "cap": 0.5,
            "block_budgets": [{"asset_class": "equity", "lo": 0.0, "hi": 0.3}],
        },
        "views": [
            {"type": "absolute", "asset": _fund_ref(0), "q": 0.20, "confidence": 0.6}
        ],
    }
    async with _client() as client:
        response = await client.post("/builder/optimize", json=payload)
    assert response.status_code == 200, response.text
    body = response.json()
    by_id = {w["asset"]["id"]: w["weight"] for w in body["weights"]}
    equity_sum = by_id[str(_FUND_IDS[0])] + by_id[str(_FUND_IDS[2])]
    assert equity_sum <= 0.3 + 1e-6
    assert body["diagnostics"]["mu_posterior"] is not None


async def test_block_budget_with_equity_maps_to_422(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _stub_returns(monkeypatch)
    _stub_asset_class(monkeypatch)
    payload = {
        "assets": [_fund_ref(0), _fund_ref(1), {"kind": "equity", "ticker": "AAPL"}],
        "objective": "min_cvar",
        "constraints": {
            "cap": 0.5,
            "block_budgets": [{"asset_class": "equity", "lo": 0.0, "hi": 0.3}],
        },
    }
    async with _client() as client:
        response = await client.post("/builder/optimize", json=payload)
    assert response.status_code == 422
    detail = response.json()["detail"]
    assert "block budgets" in detail and "equity:AAPL" in detail


async def test_block_budget_unknown_asset_class_maps_to_422(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _stub_returns(monkeypatch)
    # Fund 1 has a NULL asset_class (the column is nullable) → fail loud.
    _stub_asset_class(
        monkeypatch,
        classes={_FUND_IDS[0]: "equity", _FUND_IDS[1]: None},
    )
    payload = {
        "assets": [_fund_ref(0), _fund_ref(1)],
        "objective": "min_cvar",
        "constraints": {
            "cap": 0.6,
            "block_budgets": [{"asset_class": "equity", "lo": 0.0, "hi": 0.3}],
        },
    }
    async with _client() as client:
        response = await client.post("/builder/optimize", json=payload)
    assert response.status_code == 422
    detail = response.json()["detail"]
    assert "known asset_class" in detail and str(_FUND_IDS[1]) in detail


async def test_block_budget_matches_no_asset_maps_to_422(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _stub_returns(monkeypatch)
    # No fund is 'cash' → the cash block matches nothing → fail loud.
    _stub_asset_class(
        monkeypatch,
        classes={_FUND_IDS[0]: "equity", _FUND_IDS[1]: "fixed_income"},
    )
    payload = {
        "assets": [_fund_ref(0), _fund_ref(1)],
        "objective": "min_cvar",
        "constraints": {
            "cap": 0.6,
            "block_budgets": [{"asset_class": "cash", "lo": 0.0, "hi": 0.3}],
        },
    }
    async with _client() as client:
        response = await client.post("/builder/optimize", json=payload)
    assert response.status_code == 422
    detail = response.json()["detail"]
    assert "matches no asset" in detail and "cash" in detail


# ── Universe optimization (filter+rank the fund universe) ────────────────────


def _stub_universe(
    monkeypatch: pytest.MonkeyPatch, funds: list[optimizer_data.UniverseFund]
) -> dict[str, Any]:
    """Stub the candidate selection; capture the args the service passed."""
    captured: dict[str, Any] = {}

    async def fake_select(
        session: Any,
        filters: Any,
        *,
        rank_by: str,
        rank_dir: str,
        max_assets: int,
        require_aum: bool = False,
        window_days: int = 730,
        include_ids: Any = None,
        **_: Any,
    ) -> list[optimizer_data.UniverseFund]:
        captured.update(
            filters=filters,
            rank_by=rank_by,
            rank_dir=rank_dir,
            max_assets=max_assets,
            require_aum=require_aum,
            window_days=window_days,
            include_ids=include_ids,
        )
        return funds

    monkeypatch.setattr(optimizer_data, "select_universe_funds", fake_select)
    return captured


def _universe_funds(n: int) -> list[optimizer_data.UniverseFund]:
    return [
        optimizer_data.UniverseFund(id=_FUND_IDS[i], ticker=f"TIC{i}", name=f"Fund {i}")
        for i in range(n)
    ]


async def test_optimize_universe_min_cvar_happy_path(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _stub_returns(monkeypatch)
    captured = _stub_universe(monkeypatch, _universe_funds(4))
    payload = {
        "universe": {"fund_type": "etf", "aum_min": 1e8, "max_assets": 4},
        "objective": "min_cvar",
    }
    async with _client() as client:
        response = await client.post("/builder/optimize", json=payload)
    assert response.status_code == 200, response.text
    body = response.json()
    assert len(body["weights"]) == 4
    assert abs(sum(w["weight"] for w in body["weights"]) - 1.0) < 1e-6
    # Universe results are self-describing (the client never saw the funds).
    assert {w["ticker"] for w in body["weights"]} == {"TIC0", "TIC1", "TIC2", "TIC3"}
    assert all(w["name"] for w in body["weights"])
    assert all(w["asset"]["kind"] == "fund" for w in body["weights"])
    # min_cvar without views needs no market weights → AUM not required.
    assert captured["require_aum"] is False
    assert captured["max_assets"] == 4
    assert captured["rank_by"] == "aum_usd"


async def test_optimize_universe_bl_utility_requires_aum(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _stub_returns(monkeypatch)
    _stub_aum(monkeypatch)
    captured = _stub_universe(monkeypatch, _universe_funds(4))
    payload = {
        "universe": {"rank_by": "sharpe_1y", "max_assets": 12},
        "objective": "bl_utility",
        "constraints": {"cap": None},
    }
    async with _client() as client:
        response = await client.post("/builder/optimize", json=payload)
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["diagnostics"]["mu_equilibrium"] is not None
    assert body["diagnostics"]["mu_posterior"] is None
    # bl_utility needs equilibrium market weights → candidates must have AUM.
    assert captured["require_aum"] is True
    assert captured["rank_by"] == "sharpe_1y"


async def test_optimize_universe_with_include_instrument_ids_prunes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _stub_returns(monkeypatch)
    # The pruned set the user kept (2 of the previewed candidates).
    kept = [_FUND_IDS[0], _FUND_IDS[2]]
    captured = _stub_universe(
        monkeypatch,
        [
            optimizer_data.UniverseFund(id=fid, ticker=f"TIC{i}", name=f"Fund {i}")
            for i, fid in zip((0, 2), kept, strict=True)
        ],
    )
    payload = {
        "universe": {
            "fund_type": "etf",
            "max_assets": 10,
            "include_instrument_ids": [str(_FUND_IDS[0]), str(_FUND_IDS[2])],
        },
        "objective": "min_cvar",
        # 2 kept assets need a cap > 0.5 to leave a feasible long-only simplex.
        "constraints": {"cap": 0.6},
    }
    async with _client() as client:
        response = await client.post("/builder/optimize", json=payload)
    assert response.status_code == 200, response.text
    body = response.json()
    # Weights cover exactly the pruned funds.
    assert {w["ticker"] for w in body["weights"]} == {"TIC0", "TIC2"}
    assert len(body["weights"]) == 2
    # The kept ids were forwarded to the candidate resolver.
    assert captured["include_ids"] == [str(_FUND_IDS[0]), str(_FUND_IDS[2])]


async def test_optimize_universe_include_ids_single_element_rejected() -> None:
    payload = {
        "universe": {
            "max_assets": 10,
            "include_instrument_ids": [str(_FUND_IDS[0])],
        },
        "objective": "min_cvar",
    }
    async with _client() as client:
        response = await client.post("/builder/optimize", json=payload)
    # Field(min_length=2) → a 1-element pruned list is a validation error.
    assert response.status_code == 422


async def test_optimize_universe_too_few_candidates_maps_to_422(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _stub_universe(monkeypatch, _universe_funds(1))
    payload = {"universe": {"fund_type": "mmf"}}
    async with _client() as client:
        response = await client.post("/builder/optimize", json=payload)
    assert response.status_code == 422
    assert "universe selection matched 1" in response.json()["detail"]


async def test_optimize_requires_exactly_one_asset_source() -> None:
    async with _client() as client:
        neither = await client.post("/builder/optimize", json={"objective": "min_cvar"})
        both = await client.post(
            "/builder/optimize",
            json={"assets": [_fund_ref(0), _fund_ref(1)], "universe": {}},
        )
    assert neither.status_code == 422
    assert both.status_code == 422


async def test_optimize_universe_with_views_rejected() -> None:
    payload = {
        "universe": {"max_assets": 5},
        "views": [
            {"type": "absolute", "asset": _fund_ref(0), "q": 0.1, "confidence": 0.5}
        ],
    }
    async with _client() as client:
        response = await client.post("/builder/optimize", json=payload)
    assert response.status_code == 422


def test_humanize_error_makes_infeasible_actionable() -> None:
    from app.services.portfolio_builder import humanize_error

    out = humanize_error("min_vol: solver status 'infeasible' (expected 'optimal')")
    assert "constraint" in out.lower()
    # Fail-loud: the original technical message is preserved verbatim.
    assert "solver status 'infeasible'" in out


def test_humanize_error_passes_actionable_messages_through() -> None:
    from app.services.portfolio_builder import humanize_error

    msg = "insufficient common history: 120 overlapping observations"
    assert humanize_error(msg) == msg


async def test_optimize_turnover_penalty_stays_near_current(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _stub_returns(monkeypatch)
    base = {
        "assets": [_fund_ref(i) for i in range(4)],
        "objective": "min_cvar",
        "constraints": {"cap": None},
    }
    current = {f"fund:{_FUND_IDS[i]}": 0.25 for i in range(4)}
    async with _client() as client:
        free = await client.post("/builder/optimize", json=base)
        sticky = await client.post(
            "/builder/optimize",
            json={**base, "turnover_lambda": 8.0, "current_weights": current},
        )
    assert free.status_code == 200, free.text
    assert sticky.status_code == 200, sticky.text
    free_w = {w["asset"]["id"]: w["weight"] for w in free.json()["weights"]}
    sticky_w = {w["asset"]["id"]: w["weight"] for w in sticky.json()["weights"]}
    free_l1 = sum(abs(free_w[str(_FUND_IDS[i])] - 0.25) for i in range(4))
    sticky_l1 = sum(abs(sticky_w[str(_FUND_IDS[i])] - 0.25) for i in range(4))
    assert sticky_l1 < free_l1


async def test_optimize_max_return_cvar_with_views_happy_path(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _stub_returns(monkeypatch)
    _stub_aum(monkeypatch)
    payload = {
        "assets": [_fund_ref(i) for i in range(4)],
        "objective": "max_return_cvar",
        "cvar_limit": 0.10,
        "views": [
            {"type": "absolute", "asset": _fund_ref(0), "q": 0.15, "confidence": 0.6}
        ],
    }
    async with _client() as client:
        response = await client.post("/builder/optimize", json=payload)
    assert response.status_code == 200, response.text
    body = response.json()
    assert abs(sum(w["weight"] for w in body["weights"]) - 1.0) < 1e-6
    assert body["diagnostics"]["mu_posterior"] is not None
    assert body["diagnostics"]["status"] == "optimal"


async def test_optimize_max_return_cvar_without_bl_inputs_is_422(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _stub_returns(monkeypatch)
    payload = {
        "assets": [_fund_ref(i) for i in range(4)],
        "objective": "max_return_cvar",
        "cvar_limit": 0.10,
    }
    async with _client() as client:
        response = await client.post("/builder/optimize", json=payload)
    assert response.status_code == 422, response.text
    assert "expected returns" in response.text.lower()


async def test_optimize_max_return_cvar_risk_off_smoke(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _stub_returns(monkeypatch)
    _stub_aum(monkeypatch)
    from app.services import portfolio_builder

    monkeypatch.setattr(portfolio_builder, "_OVERRIDE_REGIME_STATE", "risk_off", raising=False)
    payload = {
        "assets": [_fund_ref(i) for i in range(4)],
        "objective": "max_return_cvar",
        "cvar_limit": 0.20,
        "views": [
            {"type": "absolute", "asset": _fund_ref(0), "q": 0.15, "confidence": 0.6}
        ],
    }
    async with _client() as client:
        response = await client.post("/builder/optimize", json=payload)
    monkeypatch.setattr(portfolio_builder, "_OVERRIDE_REGIME_STATE", None, raising=False)
    assert response.status_code == 200, response.text
    assert abs(sum(w["weight"] for w in response.json()["weights"]) - 1.0) < 1e-6


# --- T1C: builder in-sample CVaR uses the exact RU estimator ------------------

from app.analytics import historical_cvar, realized_cvar  # noqa: E402
from app.optimizer import engine  # noqa: E402


def _stub_returns_30(monkeypatch: pytest.MonkeyPatch) -> None:
    """30-obs stub: (1-0.95)*30 = 1.5 -> non-integer tail, so the exact RU
    estimator and the naive tail-mean DIFFER (unlike the 500-obs stub where
    25 is integer and they coincide). Identical RNG recipe to _stub_returns."""

    async def fake_load(
        session: Any,
        assets: list[optimizer_data.AssetRef],
        window_days: int = 730,
        today: dt.date | None = None,
    ) -> pd.DataFrame:
        rng = np.random.default_rng(11)
        index = pd.bdate_range("2024-01-02", periods=30)
        data = {
            ref.label: rng.normal(0.0003, 0.008 + 0.002 * i, 30)
            for i, ref in enumerate(assets)
        }
        return pd.DataFrame(data, index=index)

    monkeypatch.setattr(optimizer_data, "load_aligned_returns", fake_load)


async def test_builder_reports_ru_in_sample_cvar_not_tail_mean(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The /builder/optimize response reports the exact Rockafellar–Uryasev
    in-sample CVaR (consistent with the min-CVaR objective), not the naive
    tail-mean. The two differ on this 30-obs (non-integer tail) fixture."""
    _stub_returns_30(monkeypatch)
    payload = {
        "assets": [_fund_ref(i) for i in range(4)],
        "objective": "min_cvar",
    }
    async with _client() as client:
        response = await client.post("/builder/optimize", json=payload)
    assert response.status_code == 200, response.text
    reported = response.json()["expected"]["cvar_95_in_sample"]
    assert response.json()["diagnostics"]["n_obs"] == 30

    # Reconstruct the builder's post-solve report from the IDENTICAL stub: same
    # RNG -> same scenarios -> deterministic solve -> portfolio_daily.
    rng = np.random.default_rng(11)
    index = pd.bdate_range("2024-01-02", periods=30)
    refs = [
        optimizer_data.FundAssetRef(id=_FUND_IDS[i]) for i in range(4)
    ]
    frame = pd.DataFrame(
        {
            ref.label: rng.normal(0.0003, 0.008 + 0.002 * i, 30)
            for i, ref in enumerate(refs)
        },
        index=index,
    )
    scenarios = frame.to_numpy(dtype=float)
    weights, status = engine.solve_min_cvar(scenarios, cap=0.25, min_weight=None)
    assert status == "optimal"
    portfolio_daily = pd.Series(scenarios @ weights, index=frame.index)

    ru = realized_cvar(portfolio_daily, confidence=0.95)
    naive = historical_cvar(portfolio_daily, confidence=0.95)

    # The estimators disagree on this fixture (the swap is observable).
    assert ru != pytest.approx(naive, abs=1e-9)
    # The builder reports the RU value (optimizer-consistent), not the tail-mean.
    assert reported == pytest.approx(ru, abs=1e-12)
    assert reported != pytest.approx(naive, abs=1e-9)
