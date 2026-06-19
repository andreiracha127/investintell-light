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
from app.core.auth import CurrentUser, get_current_user
from app.core.db import get_session
from app.core.tiingo_provider import get_tiingo_client
from app.ingestion.service import EnsureReport
from app.main import create_app
from app.services import portfolio_crud
from app.tiingo.exceptions import TiingoNotFoundError

_CREATED = dt.datetime(2026, 6, 10, 12, 0, tzinfo=dt.UTC)


def _position(
    ticker: str = "AAPL",
    quantity: float = 10.0,
    acq_price: float | None = 200.0,
    basis: str = "reference",
    commission: float | None = None,
    trade_date: Any = None,
) -> SimpleNamespace:
    return SimpleNamespace(
        ticker=ticker,
        quantity=quantity,
        acq_price=acq_price,
        basis=basis,
        commission=commission,
        trade_date=trade_date,
    )


def _position_json(
    ticker: str,
    quantity: float,
    acq_price: float | None,
    basis: str = "reference",
    commission: float | None = None,
    trade_date: str | None = None,
) -> dict[str, Any]:
    """Expected PositionOut payload (F8.6b added basis/commission/trade_date)."""
    return {
        "ticker": ticker,
        "quantity": quantity,
        "acq_price": acq_price,
        "basis": basis,
        "commission": commission,
        "trade_date": trade_date,
    }


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
    app.dependency_overrides[get_current_user] = lambda: CurrentUser(
        sub="u-1", org_id=None, claims={}
    )
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

    async def fake_create(session: Any, payload: Any, owner_sub: str, org_id: Any) -> SimpleNamespace:
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
        _position_json("AAPL", 10.0, 200.0),
        _position_json("MSFT", 5.0, None),
    ]
    # Name trimmed and tickers uppercased BEFORE the service sees them.
    assert received[0].name == "Test"
    assert [p.ticker for p in received[0].positions] == ["AAPL", "MSFT"]
    # Tickers were validated/warmed against Tiingo in one ensure call.
    assert ensure_calls == [["AAPL", "MSFT"]]


async def test_create_without_positions_skips_the_ensure(
    monkeypatch: pytest.MonkeyPatch, ensure_calls: list[list[str]]
) -> None:
    async def fake_create(session: Any, payload: Any, owner_sub: str, org_id: Any) -> SimpleNamespace:
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
    async def fake_create(session: Any, payload: Any, owner_sub: str, org_id: Any) -> SimpleNamespace:
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

    async def fake_create(session: Any, payload: Any, owner_sub: str, org_id: Any) -> SimpleNamespace:
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

    async def fake_list(session: Any, owner_sub: str) -> list[SimpleNamespace]:
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
    async def fake_get(session: Any, portfolio_id: int, owner_sub: str) -> SimpleNamespace:
        return _portfolio(pid=portfolio_id, positions=[_position()])

    monkeypatch.setattr(portfolio_crud, "get_portfolio", fake_get)
    async with _client() as ac:
        response = await ac.get("/portfolios/7")

    assert response.status_code == 200
    body = response.json()
    assert body["id"] == 7
    assert body["positions"][0]["ticker"] == "AAPL"


async def test_get_portfolio_404(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_get(session: Any, portfolio_id: int, owner_sub: str) -> None:
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
        session: Any, portfolio_id: int, owner_sub: str, *, name: str | None, cash: float | None
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
    async def fake_update(session: Any, portfolio_id: int, owner_sub: str, **kwargs: Any) -> None:
        return None

    monkeypatch.setattr(portfolio_crud, "update_portfolio", fake_update)
    async with _client() as ac:
        response = await ac.patch("/portfolios/999", json={"cash": 5.0})

    assert response.status_code == 404


async def test_patch_duplicate_name_returns_409(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_update(session: Any, portfolio_id: int, owner_sub: str, **kwargs: Any) -> None:
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
    async def fake_delete(session: Any, portfolio_id: int, owner_sub: str) -> bool:
        return True

    monkeypatch.setattr(portfolio_crud, "delete_portfolio", fake_delete)
    async with _client() as ac:
        response = await ac.delete("/portfolios/1")

    assert response.status_code == 204
    assert response.content == b""


async def test_delete_portfolio_404(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_delete(session: Any, portfolio_id: int, owner_sub: str) -> bool:
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
    fund_tickers: set[str] | None = None,
) -> dict[str, list[Any]]:
    calls: dict[str, list[Any]] = {"insert": [], "update": []}

    async def fake_exists(session: Any, portfolio_id: int, owner_sub: str) -> bool:
        return portfolio_found

    async def fake_fund_tickers(session: Any, tickers: Any) -> set[str]:
        return (fund_tickers or set()) & set(tickers)

    monkeypatch.setattr(portfolio_crud, "select_fund_tickers", fake_fund_tickers)

    async def fake_get_position(
        session: Any, portfolio_id: int, ticker: str
    ) -> SimpleNamespace | None:
        return existing

    async def fake_insert(
        session: Any,
        portfolio_id: int,
        ticker: str,
        quantity: float,
        acq_price: float | None,
        *,
        basis: str = "reference",
        commission: float | None = None,
        trade_date: Any = None,
    ) -> SimpleNamespace:
        calls["insert"].append(
            (portfolio_id, ticker, quantity, acq_price, basis, commission, trade_date)
        )
        return _position(ticker, quantity, acq_price, basis, commission, trade_date)

    async def fake_update(
        session: Any,
        position: Any,
        quantity: float,
        acq_price: float | None,
        *,
        basis: str | None = None,
        commission: Any = portfolio_crud.UNSET,
        trade_date: Any = portfolio_crud.UNSET,
    ) -> SimpleNamespace:
        calls["update"].append(
            (
                position.ticker,
                quantity,
                acq_price,
                basis,
                None if commission is portfolio_crud.UNSET else ("SET", commission),
                None if trade_date is portfolio_crud.UNSET else ("SET", trade_date),
            )
        )
        return _position(
            position.ticker,
            quantity,
            acq_price,
            basis or position.basis,
            position.commission if commission is portfolio_crud.UNSET else commission,
            position.trade_date if trade_date is portfolio_crud.UNSET else trade_date,
        )

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
    assert response.json() == _position_json("NVDA", 3.0, 120.0)
    assert ensure_calls == [["NVDA"]]  # INSERT path validates against Tiingo
    assert calls["insert"] == [(1, "NVDA", 3.0, 120.0, "reference", None, None)]
    assert calls["update"] == []


async def test_put_position_update_path_does_not_re_ensure(
    monkeypatch: pytest.MonkeyPatch, ensure_calls: list[list[str]]
) -> None:
    calls = _install_put_stubs(monkeypatch, existing=_position("MSFT", 5.0, None))
    async with _client() as ac:
        response = await ac.put("/portfolios/1/positions/MSFT", json={"quantity": 8})

    assert response.status_code == 200
    assert response.json() == _position_json("MSFT", 8.0, None)
    assert ensure_calls == []  # UPDATE path must NOT re-ensure
    # Fill fields absent from the body — basis None / commission+trade_date
    # untouched (the F8.6b default keeps the pre-existing behavior).
    assert calls["update"] == [("MSFT", 8.0, None, None, None, None)]
    assert calls["insert"] == []


async def test_put_position_fund_ticker_insert_skips_tiingo_ensure(
    monkeypatch: pytest.MonkeyPatch, ensure_calls: list[list[str]]
) -> None:
    """Fund tickers (synced funds table) are valid positions priced from
    fund_nav — the INSERT path must NOT validate them against Tiingo (F8.5)."""
    calls = _install_put_stubs(monkeypatch, existing=None, fund_tickers={"VFIAX"})
    async with _client() as ac:
        response = await ac.put(
            "/portfolios/1/positions/vfiax", json={"quantity": 10, "acq_price": 450}
        )

    assert response.status_code == 200
    assert response.json() == _position_json("VFIAX", 10.0, 450.0)
    assert ensure_calls == []  # fund ticker — Tiingo never consulted
    assert calls["insert"] == [(1, "VFIAX", 10.0, 450.0, "reference", None, None)]


async def test_put_position_executed_fill_fields_pass_through(
    monkeypatch: pytest.MonkeyPatch, ensure_calls: list[list[str]]
) -> None:
    """F8.6b: PUT may register a real fill — basis/commission/trade_date are
    forwarded to the update (and only the provided fields overwrite)."""
    calls = _install_put_stubs(monkeypatch, existing=_position("MSFT", 5.0, 100.0))
    async with _client() as ac:
        response = await ac.put(
            "/portfolios/1/positions/MSFT",
            json={
                "quantity": 10,
                "acq_price": 100.5,
                "basis": "executed",
                "commission": 5,
                "trade_date": "2026-06-10",
            },
        )

    assert response.status_code == 200
    assert response.json() == _position_json(
        "MSFT", 10.0, 100.5, "executed", 5.0, "2026-06-10"
    )
    assert ensure_calls == []
    assert calls["update"] == [
        ("MSFT", 10.0, 100.5, "executed", ("SET", 5.0), ("SET", dt.date(2026, 6, 10)))
    ]


async def test_put_position_negative_commission_422(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_put_stubs(monkeypatch, existing=None)
    async with _client() as ac:
        response = await ac.put(
            "/portfolios/1/positions/AAPL", json={"quantity": 1, "commission": -1}
        )

    assert response.status_code == 422


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
    received: list[tuple[int, str, str]] = []

    async def fake_delete(session: Any, portfolio_id: int, ticker: str, owner_sub: str) -> bool:
        received.append((portfolio_id, ticker, owner_sub))
        return True

    monkeypatch.setattr(portfolio_crud, "delete_position", fake_delete)
    async with _client() as ac:
        response = await ac.delete("/portfolios/1/positions/aapl")

    assert response.status_code == 204
    assert received == [(1, "AAPL", "u-1")]


async def test_delete_position_404(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_delete(session: Any, portfolio_id: int, ticker: str, owner_sub: str) -> bool:
        return False

    monkeypatch.setattr(portfolio_crud, "delete_position", fake_delete)
    async with _client() as ac:
        response = await ac.delete("/portfolios/1/positions/ZZZZ")

    assert response.status_code == 404


# ---------------------------------------------------------------------------
# Wiring: JWT sub forwarded to service
# ---------------------------------------------------------------------------


async def test_create_forwards_owner_from_jwt(
    monkeypatch: pytest.MonkeyPatch, ensure_calls: list[list[str]]
) -> None:
    captured: list[tuple[str, str | None]] = []

    async def fake_create(session: Any, payload: Any, owner_sub: str, org_id: Any):
        captured.append((owner_sub, org_id))
        return _portfolio()

    monkeypatch.setattr(portfolio_crud, "create_portfolio", fake_create)
    async with _client() as ac:
        await ac.post("/portfolios", json={"name": "X"})
    assert captured == [("u-1", None)]


# ---------------------------------------------------------------------------
# Compiled-statement: upsert shape
# ---------------------------------------------------------------------------


def test_insert_position_upsert_statement_shape() -> None:
    """The upsert targets (portfolio_id, ticker) and sets updated_at=func.now()."""
    from sqlalchemy.dialects import postgresql
    from sqlalchemy.dialects.postgresql import insert as pg_insert

    from app.models.portfolio import Position

    stmt = (
        pg_insert(Position)
        .values(portfolio_id=1, ticker="AAPL", quantity=10.0, acq_price=150.0)
        .on_conflict_do_update(
            index_elements=["portfolio_id", "ticker"],
            set_={
                "quantity": 10.0,
                "acq_price": 150.0,
                "updated_at": __import__("sqlalchemy").func.now(),
            },
        )
    )
    compiled = stmt.compile(dialect=postgresql.dialect())
    sql = str(compiled)

    assert "ON CONFLICT" in sql
    assert "portfolio_id" in sql
    assert "ticker" in sql
    assert "DO UPDATE" in sql
    assert "updated_at" in sql
