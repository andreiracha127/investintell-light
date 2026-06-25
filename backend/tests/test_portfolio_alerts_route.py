"""Tests for the per-portfolio drift alerts route (GET /portfolios/{id}/alerts).

The drift status service is stubbed at its canonical module
(``app.services.portfolio_drift``) and ``portfolio_crud.portfolio_exists`` is
stubbed for the 404 gate. No live DB, no live network — same harness as the
constraints route test (TestClient / fake session / auth override).
"""

import datetime as dt
from typing import Any

import pytest
from httpx import ASGITransport, AsyncClient

from app.core.auth import CurrentUser, get_current_user
from app.core.db import get_session
from app.core.tiingo_provider import get_tiingo_client
from app.main import create_app
from app.services import portfolio_crud, portfolio_drift
from app.services.portfolio_drift import DriftStatus


class _FakeSession:
    """Minimal stand-in for AsyncSession: the route owns the commit boundary."""

    async def commit(self) -> None:  # noqa: D401 - trivial no-op
        return None


def _client() -> AsyncClient:
    app = create_app()
    app.dependency_overrides[get_session] = lambda: _FakeSession()
    app.dependency_overrides[get_tiingo_client] = lambda: object()
    app.dependency_overrides[get_current_user] = lambda: CurrentUser(
        sub="u-1", org_id=None, claims={}
    )
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


def _install_store(
    monkeypatch: pytest.MonkeyPatch,
    *,
    existing_ids: set[int] | None = None,
) -> dict[int, DriftStatus]:
    """Wire an in-memory drift-status store + a portfolio_exists gate.

    ``existing_ids`` is the set of portfolio ids considered to exist. By
    default {1} exists (so GET there succeeds).
    """
    store: dict[int, DriftStatus] = {}
    ids = {1} if existing_ids is None else existing_ids

    async def fake_exists(
        session: Any, portfolio_id: int, owner_sub: str | None = None
    ) -> bool:
        return portfolio_id in ids

    async def fake_get(session: Any, portfolio_id: int) -> DriftStatus | None:
        return store.get(portfolio_id)

    monkeypatch.setattr(portfolio_crud, "portfolio_exists", fake_exists)
    monkeypatch.setattr(portfolio_drift, "get_drift_status", fake_get)
    return store


async def test_get_alerts_reflects_persisted_status(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """After a drift status is persisted, GET reflects worst_status + breaches."""
    store = _install_store(monkeypatch)
    evaluated_at = dt.datetime(2026, 6, 20, 12, 0, tzinfo=dt.UTC)
    store[1] = DriftStatus(
        portfolio_id=1,
        evaluated_at=evaluated_at,
        worst_status="urgent",
        breaches={
            "position_drifts": [
                {"ticker": "AAPL", "current": 0.4, "target": 0.2, "status": "urgent"}
            ],
            "class_breaches": [
                {"asset_class": "equity", "current_weight": 0.9, "kind": "above_max"}
            ],
            "overlap_breaches": [
                {"security_key": "MSFT", "exposure": 0.7, "overlap_cap": 0.6}
            ],
            "overlap_report_date": "2026-05-31",
        },
    )

    async with _client() as ac:
        response = await ac.get("/portfolios/1/alerts")

    assert response.status_code == 200
    body = response.json()
    assert body["worst_status"] == "urgent"
    assert dt.datetime.fromisoformat(body["evaluated_at"]) == evaluated_at
    breaches = body["breaches"]
    assert breaches["position_drifts"][0]["ticker"] == "AAPL"
    assert breaches["class_breaches"][0]["asset_class"] == "equity"
    assert breaches["overlap_breaches"][0]["security_key"] == "MSFT"
    assert breaches["overlap_report_date"] == "2026-05-31"


async def test_get_alerts_empty_set_when_never_evaluated(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Portfolio exists but has no drift status yet -> 200 empty set."""
    _install_store(monkeypatch)
    async with _client() as ac:
        response = await ac.get("/portfolios/1/alerts")

    assert response.status_code == 200
    assert response.json() == {
        "evaluated_at": None,
        "worst_status": "ok",
        "breaches": {
            "position_drifts": [],
            "class_breaches": [],
            "overlap_breaches": [],
            "overlap_report_date": None,
        },
    }


async def test_get_alerts_404_when_portfolio_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_store(monkeypatch, existing_ids=set())
    async with _client() as ac:
        response = await ac.get("/portfolios/999/alerts")

    assert response.status_code == 404
    assert "not found" in response.json()["detail"]
