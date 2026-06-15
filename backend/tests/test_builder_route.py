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
