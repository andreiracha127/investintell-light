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
