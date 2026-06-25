"""Tests for the per-portfolio constraints routes (GET/PUT).

The constraint persistence service is stubbed at its canonical module
(``app.services.portfolio_constraints``) and ``portfolio_crud.portfolio_exists``
is stubbed for the 404 gate. No live DB, no live network.

Round-trip semantics are exercised against an in-memory fake store so PUT
followed by GET reflects exactly what was written.
"""

from typing import Any

import pytest
from httpx import ASGITransport, AsyncClient

from app.core.auth import CurrentUser, get_current_user
from app.core.db import get_session
from app.core.tiingo_provider import get_tiingo_client
from app.main import create_app
from app.services import portfolio_constraints, portfolio_crud
from app.services.portfolio_constraints import ClassLimit, ConstraintSet


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
) -> dict[int, ConstraintSet]:
    """Wire an in-memory constraint store + a portfolio_exists gate.

    ``existing_ids`` is the set of portfolio ids considered to exist. By
    default {1} exists (so PUT/GET there succeed).
    """
    store: dict[int, ConstraintSet] = {}
    ids = {1} if existing_ids is None else existing_ids

    async def fake_exists(
        session: Any, portfolio_id: int, owner_sub: str | None = None
    ) -> bool:
        return portfolio_id in ids

    async def fake_get(session: Any, portfolio_id: int) -> ConstraintSet | None:
        return store.get(portfolio_id)

    async def fake_upsert(
        session: Any,
        portfolio_id: int,
        *,
        cap: float | None,
        min_weight: float | None,
        overlap_cap: float | None,
        class_limits: list[tuple[str, float | None, float | None]],
    ) -> None:
        store[portfolio_id] = ConstraintSet(
            portfolio_id=portfolio_id,
            cap=cap,
            min_weight=min_weight,
            overlap_cap=overlap_cap,
            class_limits=[
                ClassLimit(asset_class=ac, min_weight=lo, max_weight=hi)
                for ac, lo, hi in class_limits
            ],
        )

    monkeypatch.setattr(portfolio_crud, "portfolio_exists", fake_exists)
    monkeypatch.setattr(portfolio_constraints, "get_constraints", fake_get)
    monkeypatch.setattr(portfolio_constraints, "upsert_constraints", fake_upsert)
    return store


# ---------------------------------------------------------------------------
# GET /portfolios/{id}/constraints
# ---------------------------------------------------------------------------


async def test_get_constraints_empty_set_when_none_persisted(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Portfolio exists but has no constraints yet -> 200 with an empty set."""
    _install_store(monkeypatch)
    async with _client() as ac:
        response = await ac.get("/portfolios/1/constraints")

    assert response.status_code == 200
    body = response.json()
    assert body == {
        "portfolio_id": 1,
        "cap": None,
        "min_weight": None,
        "overlap_cap": None,
        "class_limits": [],
    }


async def test_get_constraints_404_when_portfolio_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_store(monkeypatch, existing_ids=set())
    async with _client() as ac:
        response = await ac.get("/portfolios/999/constraints")

    assert response.status_code == 404
    assert "not found" in response.json()["detail"]


# ---------------------------------------------------------------------------
# PUT /portfolios/{id}/constraints
# ---------------------------------------------------------------------------


async def test_put_then_get_round_trips(monkeypatch: pytest.MonkeyPatch) -> None:
    _install_store(monkeypatch)
    payload = {
        "cap": 0.4,
        "min_weight": 0.01,
        "overlap_cap": 0.6,
        "class_limits": [
            {"asset_class": "equity", "min_weight": 0.2, "max_weight": 0.8},
            {"asset_class": "fixed_income", "min_weight": None, "max_weight": 0.3},
        ],
    }
    async with _client() as ac:
        put = await ac.put("/portfolios/1/constraints", json=payload)
        assert put.status_code == 200

        get = await ac.get("/portfolios/1/constraints")

    assert get.status_code == 200
    body = get.json()
    assert body["portfolio_id"] == 1
    assert body["cap"] == 0.4
    assert body["min_weight"] == 0.01
    assert body["overlap_cap"] == 0.6
    assert body["class_limits"] == [
        {"asset_class": "equity", "min_weight": 0.2, "max_weight": 0.8},
        {"asset_class": "fixed_income", "min_weight": None, "max_weight": 0.3},
    ]


async def test_put_nulls_round_trip_to_empty_set(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_store(monkeypatch)
    async with _client() as ac:
        put = await ac.put(
            "/portfolios/1/constraints",
            json={
                "cap": None,
                "min_weight": None,
                "overlap_cap": None,
                "class_limits": [],
            },
        )
        assert put.status_code == 200
        get = await ac.get("/portfolios/1/constraints")

    assert get.json() == {
        "portfolio_id": 1,
        "cap": None,
        "min_weight": None,
        "overlap_cap": None,
        "class_limits": [],
    }


async def test_put_class_limit_min_gt_max_returns_422(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_store(monkeypatch)
    async with _client() as ac:
        response = await ac.put(
            "/portfolios/1/constraints",
            json={
                "class_limits": [
                    {"asset_class": "equity", "min_weight": 0.8, "max_weight": 0.2}
                ]
            },
        )

    assert response.status_code == 422


async def test_put_missing_portfolio_returns_404(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_store(monkeypatch, existing_ids=set())
    async with _client() as ac:
        response = await ac.put(
            "/portfolios/999/constraints",
            json={"cap": 0.4, "class_limits": []},
        )

    assert response.status_code == 404


@pytest.mark.parametrize(
    "payload",
    [
        {"cap": 0.0},
        {"cap": 1.5},
        {"overlap_cap": 0.0},
        {"overlap_cap": 1.1},
        {"min_weight": -0.1},
        {"min_weight": 1.2},
        {"class_limits": [{"asset_class": "equity", "max_weight": 1.5}]},
        {"class_limits": [{"asset_class": "equity", "min_weight": -0.1}]},
        {"class_limits": [{"asset_class": "not_a_class", "max_weight": 0.5}]},
    ],
    ids=[
        "cap_zero",
        "cap_above_one",
        "overlap_cap_zero",
        "overlap_cap_above_one",
        "min_weight_negative",
        "min_weight_above_one",
        "class_max_above_one",
        "class_min_negative",
        "bad_asset_class",
    ],
)
async def test_put_invalid_bounds_return_422(
    monkeypatch: pytest.MonkeyPatch, payload: dict[str, Any]
) -> None:
    _install_store(monkeypatch)
    async with _client() as ac:
        response = await ac.put("/portfolios/1/constraints", json=payload)

    assert response.status_code == 422
