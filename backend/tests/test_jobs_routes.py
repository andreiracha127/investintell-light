"""Tests for the async jobs routes (E3): GET /jobs/{id} + enqueue 202 paths."""

import uuid

import pytest
from httpx import ASGITransport, AsyncClient

from app.core.db import get_session
from app.main import create_app


def _client() -> AsyncClient:
    app = create_app()
    app.dependency_overrides[get_session] = lambda: None
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


@pytest.mark.asyncio
async def test_get_unknown_job_returns_404(monkeypatch):
    from app.api.routes import jobs as jobs_route

    async def _none(session, job_id):
        return None

    monkeypatch.setattr(jobs_route.jobs_service, "get_job", _none)

    async with _client() as client:
        resp = await client.get(f"/jobs/{uuid.uuid4()}")
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_get_known_job_returns_status(monkeypatch):
    from app.api.routes import jobs as jobs_route

    jid = uuid.uuid4()

    async def _found(session, job_id):
        return type(
            "J",
            (),
            {
                "id": jid,
                "status": "succeeded",
                "kind": "walk_forward",
                "result": {"ok": True},
                "error": None,
            },
        )()

    monkeypatch.setattr(jobs_route.jobs_service, "get_job", _found)

    async with _client() as client:
        resp = await client.get(f"/jobs/{jid}")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "succeeded"
    assert body["kind"] == "walk_forward"
    assert body["result"] == {"ok": True}


def _min_walk_forward_body():
    return {
        "assets": [
            {"kind": "fund", "id": "00000000-0000-0000-0000-000000000001"},
            {"kind": "fund", "id": "00000000-0000-0000-0000-000000000002"},
        ],
        "objective": "min_cvar",
        "n_splits": 16,
    }


@pytest.mark.asyncio
async def test_walk_forward_enqueues_when_large(monkeypatch):
    from app.api.routes import backtest as bt_route

    captured = {}

    async def _fake_enqueue(session, *, kind, params_hash, portfolio_id, runner):
        captured["kind"] = kind
        return type("J", (), {"id": uuid.uuid4(), "status": "pending", "kind": kind})()

    monkeypatch.setattr(bt_route.jobs_service, "should_run_async", lambda **k: True)
    monkeypatch.setattr(bt_route.jobs_service, "enqueue_job", _fake_enqueue)

    async with _client() as client:
        resp = await client.post("/backtest/walk-forward", json=_min_walk_forward_body())
    assert resp.status_code == 202
    assert resp.json()["status"] == "pending"
    assert captured["kind"] == "walk_forward"


@pytest.mark.asyncio
async def test_walk_forward_runs_sync_when_small(monkeypatch):
    from app.api.routes import backtest as bt_route
    from app.schemas.backtest import WalkForwardResponse

    monkeypatch.setattr(bt_route.jobs_service, "should_run_async", lambda **k: False)

    called = {"n": 0}

    async def _fake_run(session, payload):
        called["n"] += 1
        raise bt_route.BacktestError("stubbed sync path reached")

    monkeypatch.setattr(bt_route.backtest_service, "run_walk_forward_backtest", _fake_run)

    async with _client() as client:
        resp = await client.post("/backtest/walk-forward", json=_min_walk_forward_body())
    # sync path hit the (stubbed) service -> 422, proving no enqueue
    assert resp.status_code == 422
    assert called["n"] == 1
