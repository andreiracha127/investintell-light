"""Tests for the async broad-universe path of POST /builder/optimize
(app/api/routes/builder.py, Sprint A Task 4).

Broad-universe requests (``universe.broad_universe = True``) run in the
background: the route persists a ``pending`` job, dispatches a coroutine via
``asyncio.create_task``, and returns 202 + ``{job_id}``. A polling endpoint
``GET /builder/optimize/{job_id}`` reports status and, when terminal, the
result or error. Every other request shape stays SYNCHRONOUS (200 +
OptimizeResponse) — covered here by a ranked-universe smoke test.

No live DB: an in-memory fake AsyncSession (shared store) backs both the
request session (``get_session`` override) and the background task's own
session (``AsyncSessionLocal`` monkeypatch). The optimizer data layer is
stubbed at ``app.optimizer.data`` exactly like test_builder_route.py.
"""

from __future__ import annotations

import asyncio
import datetime as dt
import uuid
from typing import Any

import numpy as np
import pandas as pd
import pytest
from httpx import ASGITransport, AsyncClient

from app.api.routes import builder as builder_route
from app.core.db import get_session
from app.main import create_app
from app.models.optimize_job import OptimizeJob
from app.optimizer import data as optimizer_data

_FUND_IDS = [uuid.UUID(f"00000000-0000-0000-0000-00000000000{i}") for i in range(1, 6)]


# ── In-memory fake session (shared store across request + background task) ───


class _FakeAsyncSession:
    """Dict-backed async session over a SHARED store, mimicking the slice of
    AsyncSession the optimize_jobs service + route use.

    The same ``store`` instance is handed to every session so a row written by
    the background task's session is visible to the polling request's session
    (real Postgres gives this via commit; the fake shares the dict)."""

    def __init__(self, store: dict[Any, OptimizeJob]) -> None:
        self.store = store

    def add(self, obj: OptimizeJob) -> None:
        if obj.id is None:
            default = OptimizeJob.id.default
            obj.id = default.arg(None) if default is not None else uuid.uuid4()
        if obj.status is None:
            obj.status = "pending"
        now = dt.datetime.now(dt.UTC)
        if obj.created_at is None:
            obj.created_at = now
        if obj.updated_at is None:
            obj.updated_at = now
        self.store[obj.id] = obj

    async def flush(self) -> None:
        return None

    async def commit(self) -> None:
        return None

    async def get(self, model: type[OptimizeJob], pk: Any) -> OptimizeJob | None:
        if isinstance(pk, str):
            pk = uuid.UUID(pk)
        return self.store.get(pk)

    async def __aenter__(self) -> _FakeAsyncSession:
        return self

    async def __aexit__(self, *exc: Any) -> None:
        return None


@pytest.fixture
def job_store() -> dict[Any, OptimizeJob]:
    return {}


def _client(job_store: dict[Any, OptimizeJob]) -> AsyncClient:
    app = create_app()
    app.dependency_overrides[get_session] = lambda: _FakeAsyncSession(job_store)
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


@pytest.fixture(autouse=True)
def _patch_background_sessionmaker(
    monkeypatch: pytest.MonkeyPatch, job_store: dict[Any, OptimizeJob]
) -> None:
    """The background task opens its OWN session via AsyncSessionLocal; point it
    at the shared in-memory store so the job it writes is pollable."""

    def fake_sessionmaker() -> _FakeAsyncSession:
        return _FakeAsyncSession(job_store)

    monkeypatch.setattr(builder_route, "AsyncSessionLocal", fake_sessionmaker)


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


def _universe_funds(n: int) -> list[optimizer_data.UniverseFund]:
    return [
        optimizer_data.UniverseFund(id=_FUND_IDS[i], ticker=f"TIC{i}", name=f"Fund {i}")
        for i in range(n)
    ]


def _stub_universe(
    monkeypatch: pytest.MonkeyPatch, funds: list[optimizer_data.UniverseFund]
) -> None:
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
        return funds

    monkeypatch.setattr(optimizer_data, "select_universe_funds", fake_select)


def _stub_broad(monkeypatch: pytest.MonkeyPatch, n_funds: int = 12) -> None:
    """Full broad-universe pipeline stub (Stage-1 selection + Stage-2 NAV).

    Mirrors ``test_builder_broad_universe._stub_broad``: planted, well-separated
    risk clusters + the quality/risk loaders the broad branch calls on the
    session — so the two-stage math runs LIVE off deterministic data."""
    ids = [uuid.UUID(int=i + 1) for i in range(n_funds)]

    async def fake_select(session: Any, filters: Any, **kw: Any) -> list[Any]:
        return [
            optimizer_data.UniverseFund(id=i, ticker=f"F{k}", name=f"Fund {k}")
            for k, i in enumerate(ids)
        ]

    async def fake_features(
        session: Any, fund_ids: list[uuid.UUID]
    ) -> dict[uuid.UUID, dict[str, float | None]]:
        out: dict[uuid.UUID, dict[str, float | None]] = {}
        for k, fid in enumerate(fund_ids):
            base = float(k // 4) * 10.0  # 3 clusters of 4, centers 0/10/20
            out[fid] = {key: base + 0.1 * (k % 4) for key in optimizer_data.RISK_FEATURE_KEYS}
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


async def _poll_until_terminal(
    client: AsyncClient, job_id: str, *, tries: int = 50
) -> dict[str, Any]:
    """Poll GET /builder/optimize/{job_id} until the job leaves
    pending/running (the create_task coroutine runs on the same loop)."""
    for _ in range(tries):
        resp = await client.get(f"/builder/optimize/{job_id}")
        assert resp.status_code == 200, resp.text
        body = resp.json()
        if body["status"] in ("succeeded", "failed"):
            return body
        await asyncio.sleep(0.01)
    raise AssertionError(f"job {job_id} never reached a terminal state")


# ── Async broad-universe path ────────────────────────────────────────────────


async def test_broad_universe_returns_202_with_job_id(
    monkeypatch: pytest.MonkeyPatch, job_store: dict[Any, OptimizeJob]
) -> None:
    _stub_broad(monkeypatch, n_funds=12)
    payload = {
        "universe": {"fund_type": "etf", "broad_universe": True, "max_positions": 4},
        "objective": "min_cvar",
    }
    async with _client(job_store) as client:
        response = await client.post("/builder/optimize", json=payload)
    assert response.status_code == 202, response.text
    body = response.json()
    assert "job_id" in body
    # Round-trips as a UUID and a pending row exists in the store.
    job_uuid = uuid.UUID(body["job_id"])
    assert job_uuid in job_store


async def test_broad_universe_job_polls_to_succeeded_with_result(
    monkeypatch: pytest.MonkeyPatch, job_store: dict[Any, OptimizeJob]
) -> None:
    _stub_broad(monkeypatch, n_funds=12)
    payload = {
        "universe": {"fund_type": "etf", "broad_universe": True, "max_positions": 3},
        "objective": "min_cvar",
    }
    async with _client(job_store) as client:
        accepted = await client.post("/builder/optimize", json=payload)
        assert accepted.status_code == 202, accepted.text
        job_id = accepted.json()["job_id"]
        body = await _poll_until_terminal(client, job_id)

    assert body["status"] == "succeeded", body
    assert body["error"] is None
    result = body["result"]
    assert result is not None
    weights = [w["weight"] for w in result["weights"]]
    assert abs(sum(weights) - 1.0) < 1e-6
    assert result["diagnostics"]["status"] == "optimal"


async def test_broad_universe_error_path_marks_failed_verbatim(
    monkeypatch: pytest.MonkeyPatch, job_store: dict[Any, OptimizeJob]
) -> None:
    # Too few candidates → BuilderError inside run_optimize → mark_failed.
    _stub_universe(monkeypatch, _universe_funds(1))
    payload = {
        "universe": {"fund_type": "mmf", "broad_universe": True},
        "objective": "min_cvar",
    }
    async with _client(job_store) as client:
        accepted = await client.post("/builder/optimize", json=payload)
        assert accepted.status_code == 202, accepted.text
        job_id = accepted.json()["job_id"]
        body = await _poll_until_terminal(client, job_id)

    assert body["status"] == "failed", body
    assert body["result"] is None
    assert "universe selection matched 1" in body["error"]


async def test_get_unknown_job_id_returns_404(
    job_store: dict[Any, OptimizeJob],
) -> None:
    async with _client(job_store) as client:
        response = await client.get(f"/builder/optimize/{uuid.uuid4()}")
    assert response.status_code == 404


# ── Synchronous path stays unchanged ─────────────────────────────────────────


async def test_ranked_universe_stays_synchronous_200(
    monkeypatch: pytest.MonkeyPatch, job_store: dict[Any, OptimizeJob]
) -> None:
    _stub_returns(monkeypatch)
    _stub_universe(monkeypatch, _universe_funds(4))
    payload = {
        "universe": {"fund_type": "etf", "max_assets": 4},  # broad_universe defaults False
        "objective": "min_cvar",
    }
    async with _client(job_store) as client:
        response = await client.post("/builder/optimize", json=payload)
    # Synchronous: full OptimizeResponse, not a 202 job handle.
    assert response.status_code == 200, response.text
    body = response.json()
    assert "weights" in body and "job_id" not in body
    assert abs(sum(w["weight"] for w in body["weights"]) - 1.0) < 1e-6
    # No background job was created for the synchronous path.
    assert job_store == {}


async def test_explicit_assets_stays_synchronous_200(
    monkeypatch: pytest.MonkeyPatch, job_store: dict[Any, OptimizeJob]
) -> None:
    _stub_returns(monkeypatch)
    payload = {
        "assets": [{"kind": "fund", "id": str(_FUND_IDS[i])} for i in range(4)],
        "objective": "min_cvar",
    }
    async with _client(job_store) as client:
        response = await client.post("/builder/optimize", json=payload)
    assert response.status_code == 200, response.text
    assert "weights" in response.json()
    assert job_store == {}
