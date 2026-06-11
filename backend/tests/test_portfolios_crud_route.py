"""Tests for the persisted-portfolio CRUD routes (app/api/routes/portfolios.py).

The persistence service is stubbed at its canonical module
(``app.services.portfolio_crud``); the EOD ensure is stubbed at
``app.api._shared.ensure_eod_data`` so the shared HTTP error mapping stays
live. No live network, no live DB.
"""

import datetime as dt
from types import SimpleNamespace
from typing import Any

import pytest
from httpx import ASGITransport, AsyncClient

from app.api import _shared as api_shared
from app.core.db import get_session
from app.core.tiingo_provider import get_tiingo_client
from app.ingestion.service import EnsureReport
from app.main import create_app
from app.services import portfolio_crud
from app.tiingo.exceptions import TiingoNotFoundError

_CREATED = dt.datetime(2026, 6, 10, 12, 0, tzinfo=dt.UTC)


def _position(
    ticker: str = "AAPL", quantity: float = 10.0, acq_price: float | None = 200.0
) -> SimpleNamespace:
    return SimpleNamespace(ticker=ticker, quantity=quantity, acq_price=acq_price)


def _portfolio(
    pid: int = 1,
    name: str = "Test",
    cash: float = 0.0,
    positions: list[SimpleNamespace] | None = None,
) -> SimpleNamespace:
    return SimpleNamespace(
        id=pid,
        name=name,
        cash=cash,
        created_at=_CREATED,
        updated_at=_CREATED,
        positions=positions or [],
    )


def _client() -> AsyncClient:
    app = create_app()
    app.dependency_overrides[get_session] = lambda: None
    app.dependency_overrides[get_tiingo_client] = lambda: object()
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


@pytest.fixture
def ensure_calls(monkeypatch: pytest.MonkeyPatch) -> list[list[str]]:
    """Record tickers passed to the EOD ensure (mapping logic stays live)."""
    calls: list[list[str]] = []

    async def fake_ensure(
        session: Any, client: Any, tickers: list[str], start: Any, end: Any, **kwargs: Any
    ) -> EnsureReport:
        calls.append(list(tickers))
        return EnsureReport()

    monkeypatch.setattr(api_shared, "ensure_eod_data", fake_ensure)
    return calls


# ---------------------------------------------------------------------------
# POST /portfolios
# ---------------------------------------------------------------------------


async def test_create_portfolio_201_normalizes_and_ensures(
    monkeypatch: pytest.MonkeyPatch, ensure_calls: list[list[str]]
) -> None:
    received: list[Any] = []

    async def fake_create(session: Any, payload: Any) -> SimpleNamespace:
        received.append(payload)
        return _portfolio(
            positions=[_position(), _position("MSFT", 5.0, None)]
        )

    monkeypatch.setattr(portfolio_crud, "create_portfolio", fake_create)
    async with _client() as ac:
        response = await ac.post(
            "/portfolios",
            json={
                "name": "  Test  ",
                "positions": [
                    {"ticker": "aapl", "quantity": 10, "acq_price": 200},
                    {"ticker": "msft", "quantity": 5},
                ],
            },
        )

    assert response.status_code == 201
    body = response.json()
    assert body["id"] == 1
    assert body["name"] == "Test"
    assert body["cash"] == 0.0
    assert body["positions"] == [
        {"ticker": "AAPL", "quantity": 10.0, "acq_price": 200.0},
        {"ticker": "MSFT", "quantity": 5.0, "acq_price": None},
    ]
    # Name trimmed and tickers uppercased BEFORE the service sees them.
    assert received[0].name == "Test"
    assert [p.ticker for p in received[0].positions] == ["AAPL", "MSFT"]
    # Tickers were validated/warmed against Tiingo in one ensure call.
    assert ensure_calls == [["AAPL", "MSFT"]]


async def test_create_without_positions_skips_the_ensure(
    monkeypatch: pytest.MonkeyPatch, ensure_calls: list[list[str]]
) -> None:
    async def fake_create(session: Any, payload: Any) -> SimpleNamespace:
        return _portfolio(name="Empty", cash=100.0)

    monkeypatch.setattr(portfolio_crud, "create_portfolio", fake_create)
    async with _client() as ac:
        response = await ac.post("/portfolios", json={"name": "Empty", "cash": 100.0})

    assert response.status_code == 201
    assert response.json()["positions"] == []
    assert ensure_calls == []


async def test_create_duplicate_name_returns_409(
    monkeypatch: pytest.MonkeyPatch, ensure_calls: list[list[str]]
) -> None:
    async def fake_create(session: Any, payload: Any) -> SimpleNamespace:
        raise portfolio_crud.DuplicatePortfolioNameError(
            "A portfolio named 'Test' already exists."
        )

    monkeypatch.setattr(portfolio_crud, "create_portfolio", fake_create)
    async with _client() as ac:
        response = await ac.post("/portfolios", json={"name": "Test"})

    assert response.status_code == 409
    assert "already exists" in response.json()["detail"]


async def test_create_with_tiingo_unknown_ticker_returns_404_before_persisting(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fake_ensure(*args: Any, **kwargs: Any) -> EnsureReport:
        raise TiingoNotFoundError("404 from Tiingo")

    created: list[Any] = []

    async def fake_create(session: Any, payload: Any) -> SimpleNamespace:
        created.append(payload)
        return _portfolio()

    monkeypatch.setattr(api_shared, "ensure_eod_data", fake_ensure)
    monkeypatch.setattr(portfolio_crud, "create_portfolio", fake_create)
    async with _client() as ac:
        response = await ac.post(
            "/portfolios",
            json={"name": "Typo", "positions": [{"ticker": "AAPLX", "quantity": 1}]},
        )

    assert response.status_code == 404
    assert "Unknown ticker" in response.json()["detail"]
    assert created == []  # fail loud BEFORE anything is persisted


@pytest.mark.parametrize(
    ("body", "fragment"),
    [
        ({"name": "   "}, "1..80"),
        ({"name": "x" * 81}, "1..80"),
        (
            {
                "name": "Dup",
                "positions": [
                    {"ticker": "AAPL", "quantity": 1},
                    {"ticker": "aapl", "quantity": 2},
                ],
            },
            "Duplicate tickers",
        ),
        (
            {"name": "Bad", "positions": [{"ticker": "AA$PL", "quantity": 1}]},
            "Invalid ticker",
        ),
        (
            {"name": "Qty", "positions": [{"ticker": "AAPL", "quantity": 0}]},
            "greater than 0",
        ),
        (
            {"name": "Qty", "positions": [{"ticker": "AAPL", "quantity": -3}]},
            "greater than 0",
        ),
        (
            {
                "name": "Px",
                "positions": [{"ticker": "AAPL", "quantity": 1, "acq_price": 0}],
            },
            "greater than 0",
        ),
        (
            {
                "name": "Too many",
                "positions": [
                    {"ticker": f"T{i}", "quantity": 1} for i in range(51)
                ],
            },
            "at most 50",
        ),
    ],
    ids=[
        "blank_name",
        "name_too_long",
        "duplicate_tickers",
        "bad_ticker",
        "quantity_zero",
        "quantity_negative",
        "acq_price_zero",
        "too_many_positions",
    ],
)
async def test_create_validation_errors_return_422(
    ensure_calls: list[list[str]], body: dict[str, Any], fragment: str
) -> None:
    async with _client() as ac:
        response = await ac.post("/portfolios", json=body)

    assert response.status_code == 422
    assert fragment in response.text
    assert ensure_calls == []  # rejected before any ingestion work


# ---------------------------------------------------------------------------
# GET /portfolios and GET /portfolios/{id}
# ---------------------------------------------------------------------------


async def test_list_portfolios_shape(monkeypatch: pytest.MonkeyPatch) -> None:
    rows = [
        SimpleNamespace(id=1, name="A", cash=0.0, position_count=2, created_at=_CREATED),
        SimpleNamespace(id=2, name="B", cash=50.0, position_count=0, created_at=_CREATED),
    ]

    async def fake_list(session: Any) -> list[SimpleNamespace]:
        return rows

    monkeypatch.setattr(portfolio_crud, "list_portfolios", fake_list)
    async with _client() as ac:
        response = await ac.get("/portfolios")

    assert response.status_code == 200
    body = response.json()
    assert [item["id"] for item in body] == [1, 2]
    assert set(body[0]) == {"id", "name", "cash", "position_count", "created_at"}
    assert body[0]["position_count"] == 2


async def test_get_portfolio_200(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_get(session: Any, portfolio_id: int) -> SimpleNamespace:
        return _portfolio(pid=portfolio_id, positions=[_position()])

    monkeypatch.setattr(portfolio_crud, "get_portfolio", fake_get)
    async with _client() as ac:
        response = await ac.get("/portfolios/7")

    assert response.status_code == 200
    body = response.json()
    assert body["id"] == 7
    assert body["positions"][0]["ticker"] == "AAPL"


async def test_get_portfolio_404(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_get(session: Any, portfolio_id: int) -> None:
        return None

    monkeypatch.setattr(portfolio_crud, "get_portfolio", fake_get)
    async with _client() as ac:
        response = await ac.get("/portfolios/999")

    assert response.status_code == 404
    assert "not found" in response.json()["detail"]


# ---------------------------------------------------------------------------
# PATCH /portfolios/{id}
# ---------------------------------------------------------------------------


async def test_patch_portfolio_200(monkeypatch: pytest.MonkeyPatch) -> None:
    received: list[dict[str, Any]] = []

    async def fake_update(
        session: Any, portfolio_id: int, *, name: str | None, cash: float | None
    ) -> SimpleNamespace:
        received.append({"name": name, "cash": cash})
        return _portfolio(pid=portfolio_id, name=name or "Test", cash=cash or 0.0)

    monkeypatch.setattr(portfolio_crud, "update_portfolio", fake_update)
    async with _client() as ac:
        response = await ac.patch("/portfolios/1", json={"name": "Renamed"})

    assert response.status_code == 200
    assert response.json()["name"] == "Renamed"
    assert received == [{"name": "Renamed", "cash": None}]


async def test_patch_portfolio_404(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_update(session: Any, portfolio_id: int, **kwargs: Any) -> None:
        return None

    monkeypatch.setattr(portfolio_crud, "update_portfolio", fake_update)
    async with _client() as ac:
        response = await ac.patch("/portfolios/999", json={"cash": 5.0})

    assert response.status_code == 404


async def test_patch_duplicate_name_returns_409(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_update(session: Any, portfolio_id: int, **kwargs: Any) -> None:
        raise portfolio_crud.DuplicatePortfolioNameError("taken")

    monkeypatch.setattr(portfolio_crud, "update_portfolio", fake_update)
    async with _client() as ac:
        response = await ac.patch("/portfolios/1", json={"name": "Taken"})

    assert response.status_code == 409


async def test_patch_empty_body_returns_422() -> None:
    async with _client() as ac:
        response = await ac.patch("/portfolios/1", json={})

    assert response.status_code == 422
    assert "at least one" in response.text


# ---------------------------------------------------------------------------
# DELETE /portfolios/{id}
# ---------------------------------------------------------------------------


async def test_delete_portfolio_204(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_delete(session: Any, portfolio_id: int) -> bool:
        return True

    monkeypatch.setattr(portfolio_crud, "delete_portfolio", fake_delete)
    async with _client() as ac:
        response = await ac.delete("/portfolios/1")

    assert response.status_code == 204
    assert response.content == b""


async def test_delete_portfolio_404(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_delete(session: Any, portfolio_id: int) -> bool:
        return False

    monkeypatch.setattr(portfolio_crud, "delete_portfolio", fake_delete)
    async with _client() as ac:
        response = await ac.delete("/portfolios/999")

    assert response.status_code == 404


# ---------------------------------------------------------------------------
# PUT /portfolios/{id}/positions/{ticker}
# ---------------------------------------------------------------------------


def _install_put_stubs(
    monkeypatch: pytest.MonkeyPatch,
    existing: SimpleNamespace | None,
    portfolio_found: bool = True,
) -> dict[str, list[Any]]:
    calls: dict[str, list[Any]] = {"insert": [], "update": []}

    async def fake_exists(session: Any, portfolio_id: int) -> bool:
        return portfolio_found

    async def fake_get_position(
        session: Any, portfolio_id: int, ticker: str
    ) -> SimpleNamespace | None:
        return existing

    async def fake_insert(
        session: Any, portfolio_id: int, ticker: str, quantity: float, acq_price: float | None
    ) -> SimpleNamespace:
        calls["insert"].append((portfolio_id, ticker, quantity, acq_price))
        return _position(ticker, quantity, acq_price)

    async def fake_update(
        session: Any, position: Any, quantity: float, acq_price: float | None
    ) -> SimpleNamespace:
        calls["update"].append((position.ticker, quantity, acq_price))
        return _position(position.ticker, quantity, acq_price)

    monkeypatch.setattr(portfolio_crud, "portfolio_exists", fake_exists)
    monkeypatch.setattr(portfolio_crud, "get_position", fake_get_position)
    monkeypatch.setattr(portfolio_crud, "insert_position", fake_insert)
    monkeypatch.setattr(portfolio_crud, "update_position", fake_update)
    return calls


async def test_put_position_insert_path_ensures_ticker(
    monkeypatch: pytest.MonkeyPatch, ensure_calls: list[list[str]]
) -> None:
    calls = _install_put_stubs(monkeypatch, existing=None)
    async with _client() as ac:
        response = await ac.put(
            "/portfolios/1/positions/nvda", json={"quantity": 3, "acq_price": 120}
        )

    assert response.status_code == 200
    assert response.json() == {"ticker": "NVDA", "quantity": 3.0, "acq_price": 120.0}
    assert ensure_calls == [["NVDA"]]  # INSERT path validates against Tiingo
    assert calls["insert"] == [(1, "NVDA", 3.0, 120.0)]
    assert calls["update"] == []


async def test_put_position_update_path_does_not_re_ensure(
    monkeypatch: pytest.MonkeyPatch, ensure_calls: list[list[str]]
) -> None:
    calls = _install_put_stubs(monkeypatch, existing=_position("MSFT", 5.0, None))
    async with _client() as ac:
        response = await ac.put("/portfolios/1/positions/MSFT", json={"quantity": 8})

    assert response.status_code == 200
    assert response.json() == {"ticker": "MSFT", "quantity": 8.0, "acq_price": None}
    assert ensure_calls == []  # UPDATE path must NOT re-ensure
    assert calls["update"] == [("MSFT", 8.0, None)]
    assert calls["insert"] == []


async def test_put_position_missing_portfolio_404(
    monkeypatch: pytest.MonkeyPatch, ensure_calls: list[list[str]]
) -> None:
    _install_put_stubs(monkeypatch, existing=None, portfolio_found=False)
    async with _client() as ac:
        response = await ac.put("/portfolios/999/positions/AAPL", json={"quantity": 1})

    assert response.status_code == 404
    assert ensure_calls == []


async def test_put_position_invalid_ticker_422(
    monkeypatch: pytest.MonkeyPatch, ensure_calls: list[list[str]]
) -> None:
    _install_put_stubs(monkeypatch, existing=None)
    async with _client() as ac:
        response = await ac.put(
            "/portfolios/1/positions/ABCDEFGHIJK", json={"quantity": 1}
        )

    assert response.status_code == 422
    assert "Invalid ticker" in response.json()["detail"]


@pytest.mark.parametrize("body", [{"quantity": 0}, {"quantity": 2, "acq_price": -1}])
async def test_put_position_invalid_body_422(
    monkeypatch: pytest.MonkeyPatch, body: dict[str, Any]
) -> None:
    _install_put_stubs(monkeypatch, existing=None)
    async with _client() as ac:
        response = await ac.put("/portfolios/1/positions/AAPL", json=body)

    assert response.status_code == 422


# ---------------------------------------------------------------------------
# DELETE /portfolios/{id}/positions/{ticker}
# ---------------------------------------------------------------------------


async def test_delete_position_204(monkeypatch: pytest.MonkeyPatch) -> None:
    received: list[tuple[int, str]] = []

    async def fake_delete(session: Any, portfolio_id: int, ticker: str) -> bool:
        received.append((portfolio_id, ticker))
        return True

    monkeypatch.setattr(portfolio_crud, "delete_position", fake_delete)
    async with _client() as ac:
        response = await ac.delete("/portfolios/1/positions/aapl")

    assert response.status_code == 204
    assert received == [(1, "AAPL")]


async def test_delete_position_404(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_delete(session: Any, portfolio_id: int, ticker: str) -> bool:
        return False

    monkeypatch.setattr(portfolio_crud, "delete_position", fake_delete)
    async with _client() as ac:
        response = await ac.delete("/portfolios/1/positions/ZZZZ")

    assert response.status_code == 404
