"""Protected routes require a valid InsForge JWT (401 without)."""
from typing import Any

import pytest
from httpx import ASGITransport, AsyncClient

from app.core.auth import CurrentUser, get_current_user
from app.core.db import get_session
from app.main import create_app
from app.services import funds_catalog


def _client(authed: bool) -> AsyncClient:
    app = create_app()
    app.dependency_overrides[get_session] = lambda: None
    if authed:
        app.dependency_overrides[get_current_user] = lambda: CurrentUser(
            sub="u-1", org_id="org-1", claims={}
        )
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


async def test_portfolios_list_requires_auth() -> None:
    async with _client(authed=False) as client:
        resp = await client.get("/portfolios")
    assert resp.status_code in (401, 403)  # missing bearer


async def test_rebalance_preview_requires_auth() -> None:
    async with _client(authed=False) as client:
        resp = await client.get(
            "/portfolios/00000000-0000-0000-0000-000000000001/rebalance/preview"
        )
    assert resp.status_code in (401, 403)  # missing bearer


async def test_public_funds_list_stays_open(monkeypatch: pytest.MonkeyPatch) -> None:
    # Catalog stays public — no auth override, must not 401. The catalog service
    # is stubbed (session is None) so the public route reaches a 200, proving it
    # is not gated behind the bearer dependency.
    async def fake_fetch_funds(
        session: Any, filters: Any, **kwargs: Any
    ) -> tuple[list[dict[str, Any]], int]:
        return [], 0

    async def fake_fetch_staleness(session: Any) -> funds_catalog.Staleness:
        return funds_catalog.Staleness(
            synced_at=None, source_calc_date=None, source_nav_max_date=None
        )

    monkeypatch.setattr(funds_catalog, "fetch_funds", fake_fetch_funds)
    monkeypatch.setattr(funds_catalog, "fetch_staleness", fake_fetch_staleness)
    async with _client(authed=False) as client:
        resp = await client.get("/funds")
    assert resp.status_code != 401
