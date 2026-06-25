"""Tests for the persisted portfolio transaction ledger and NAV series."""

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
from app.services import portfolio_crud, portfolio_ledger
from app.services.portfolio_ledger import (
    InsufficientPositionError,
    build_transaction_nav,
)

_CREATED = dt.datetime(2026, 6, 10, 12, 0, tzinfo=dt.UTC)


class FakeRouteSession:
    async def commit(self) -> None:
        return None

    async def rollback(self) -> None:
        return None


def _tx(
    ticker: str,
    side: str,
    quantity: float,
    price: float,
    trade_date: dt.date,
    commission: float = 0.0,
    tx_id: int = 1,
) -> SimpleNamespace:
    return SimpleNamespace(
        id=tx_id,
        portfolio_id=7,
        ticker=ticker,
        side=side,
        quantity=quantity,
        price=price,
        commission=commission,
        trade_date=trade_date,
        created_at=_CREATED,
    )


def _client() -> AsyncClient:
    app = create_app()
    app.dependency_overrides[get_session] = FakeRouteSession
    app.dependency_overrides[get_tiingo_client] = lambda: object()
    app.dependency_overrides[get_current_user] = lambda: CurrentUser(
        sub="u-1", org_id=None, claims={}
    )
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


@pytest.fixture
def ensure_calls(monkeypatch: pytest.MonkeyPatch) -> list[list[str]]:
    calls: list[list[str]] = []

    async def fake_ensure(
        session: Any, client: Any, tickers: list[str], start: Any, end: Any, **kwargs: Any
    ) -> EnsureReport:
        calls.append(list(tickers))
        return EnsureReport()

    monkeypatch.setattr(api_shared, "ensure_eod_data", fake_ensure)
    return calls


def test_build_transaction_nav_uses_real_trade_dates_and_sells() -> None:
    d1 = dt.date(2026, 1, 1)
    d2 = dt.date(2026, 1, 2)
    d3 = dt.date(2026, 1, 3)
    d4 = dt.date(2026, 1, 4)
    points = build_transaction_nav(
        [
            _tx("AAPL", "buy", 10, 100, d1),
            _tx("AAPL", "sell", 5, 120, d3),
        ],
        {"AAPL": [(d1, 100), (d2, 110), (d3, 120), (d4, 60)]},
    )

    assert [(p.date, p.nav, p.market_value, p.cash) for p in points] == [
        (d1, 100.0, 1000.0, -1000.0),
        (d2, 110.0, 1100.0, -1000.0),
        (d3, 120.0, 600.0, -400.0),
        (d4, 60.0, 300.0, -400.0),
    ]


def test_build_transaction_nav_buy_changes_future_exposure_not_same_day_return() -> None:
    d1 = dt.date(2026, 1, 1)
    d2 = dt.date(2026, 1, 2)
    d3 = dt.date(2026, 1, 3)
    points = build_transaction_nav(
        [
            _tx("AAPL", "buy", 10, 100, d1),
            _tx("AAPL", "buy", 10, 110, d2),
        ],
        {"AAPL": [(d1, 100), (d2, 110), (d3, 121)]},
    )

    assert [(p.date, p.nav, p.market_value) for p in points] == [
        (d1, 100.0, 1000.0),
        (d2, 110.0, 2200.0),
        (d3, 121.0, 2420.0),
    ]


def test_build_transaction_nav_rejects_oversell() -> None:
    d1 = dt.date(2026, 1, 1)
    with pytest.raises(InsufficientPositionError, match="Cannot sell"):
        build_transaction_nav(
            [_tx("AAPL", "sell", 1, 100, d1)],
            {"AAPL": [(d1, 100)]},
        )


async def test_seed_initial_position_buys_from_snapshot(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    inception = dt.date(2026, 1, 2)
    added: list[Any] = []
    flushed = False

    class FakeSession:
        def add(self, row: Any) -> None:
            added.append(row)

        async def flush(self) -> None:
            nonlocal flushed
            flushed = True

    async def fake_transactions(session: Any, portfolio_id: int) -> list[Any]:
        return []

    async def fake_get_portfolio(
        session: Any, portfolio_id: int, owner_sub: str | None = None
    ) -> SimpleNamespace:
        return SimpleNamespace(
            id=portfolio_id,
            inception_date=inception,
            positions=[
                SimpleNamespace(
                    ticker="AAPL",
                    quantity=10.0,
                    acq_price=100.0,
                    commission=1.25,
                    trade_date=None,
                ),
                SimpleNamespace(
                    ticker="MSFT",
                    quantity=5.0,
                    acq_price=None,
                    commission=None,
                    trade_date=dt.date(2026, 1, 3),
                ),
            ],
        )

    async def fake_closes(session: Any, tickers: Any) -> dict[str, Any]:
        assert tickers == ["MSFT"]
        return {"MSFT": [(dt.date(2026, 1, 3), 250.0)]}

    async def fake_navs(session: Any, tickers: Any) -> dict[str, Any]:
        assert tickers == []
        return {}

    monkeypatch.setattr(portfolio_ledger, "list_transactions", fake_transactions)
    monkeypatch.setattr(portfolio_crud, "get_portfolio", fake_get_portfolio)
    monkeypatch.setattr(portfolio_crud, "select_last_two_closes", fake_closes)
    monkeypatch.setattr(portfolio_crud, "select_last_two_navs", fake_navs)

    transactions = await portfolio_ledger.seed_initial_position_buys(FakeSession(), 7)

    assert transactions == added
    assert flushed is True
    assert [(tx.ticker, tx.side, tx.quantity, tx.price, tx.trade_date) for tx in added] == [
        ("AAPL", "buy", 10.0, 100.0, inception),
        ("MSFT", "buy", 5.0, 250.0, dt.date(2026, 1, 3)),
    ]
    assert float(added[0].commission) == pytest.approx(1.25)
    assert float(added[1].commission) == pytest.approx(0.0)


async def test_create_transaction_route_normalizes_ensures_and_persists(
    monkeypatch: pytest.MonkeyPatch, ensure_calls: list[list[str]]
) -> None:
    received: list[Any] = []
    materialized: list[int] = []

    async def fake_exists(
        session: Any, portfolio_id: int, owner_sub: str | None = None
    ) -> bool:
        return True

    async def fake_fund_tickers(session: Any, tickers: Any) -> set[str]:
        return set()

    async def fake_create(session: Any, portfolio_id: int, payload: Any) -> SimpleNamespace:
        received.append((portfolio_id, payload))
        return _tx(
            payload.ticker,
            payload.side,
            payload.quantity,
            payload.price,
            payload.trade_date,
            payload.commission,
        )

    async def fake_materialize(session: Any, portfolio_id: int) -> SimpleNamespace:
        materialized.append(portfolio_id)
        return SimpleNamespace(portfolio_id=portfolio_id)

    monkeypatch.setattr(portfolio_crud, "portfolio_exists", fake_exists)
    monkeypatch.setattr(portfolio_crud, "select_fund_tickers", fake_fund_tickers)
    monkeypatch.setattr(portfolio_ledger, "create_transaction", fake_create)
    monkeypatch.setattr(portfolio_ledger, "materialize_portfolio_nav", fake_materialize)

    async with _client() as ac:
        response = await ac.post(
            "/portfolios/7/transactions",
            json={
                "ticker": "aapl",
                "side": "buy",
                "quantity": 10,
                "price": 100,
                "commission": 1.5,
                "trade_date": "2026-01-01",
            },
        )

    assert response.status_code == 201, response.text
    body = response.json()
    assert body["ticker"] == "AAPL"
    assert body["side"] == "buy"
    assert body["commission"] == 1.5
    assert ensure_calls == [["AAPL"]]
    assert received[0][0] == 7
    assert received[0][1].ticker == "AAPL"
    assert materialized == [7]


async def test_create_transaction_route_skips_ensure_for_funds(
    monkeypatch: pytest.MonkeyPatch, ensure_calls: list[list[str]]
) -> None:
    materialized: list[int] = []

    async def fake_exists(
        session: Any, portfolio_id: int, owner_sub: str | None = None
    ) -> bool:
        return True

    async def fake_fund_tickers(session: Any, tickers: Any) -> set[str]:
        return {"VFIAX"}

    async def fake_taxonomy(session: Any, tickers: Any) -> dict[str, Any]:
        return {
            ticker: portfolio_crud.PositionTaxonomy(
                None, None, None, "mutual_fund"
            )
            for ticker in tickers
        }

    async def fake_create(session: Any, portfolio_id: int, payload: Any) -> SimpleNamespace:
        return _tx(
            payload.ticker,
            payload.side,
            payload.quantity,
            payload.price,
            payload.trade_date,
        )

    async def fake_materialize(session: Any, portfolio_id: int) -> SimpleNamespace:
        materialized.append(portfolio_id)
        return SimpleNamespace(portfolio_id=portfolio_id)

    monkeypatch.setattr(portfolio_crud, "portfolio_exists", fake_exists)
    monkeypatch.setattr(portfolio_crud, "select_fund_tickers", fake_fund_tickers)
    monkeypatch.setattr(portfolio_crud, "resolve_position_taxonomy", fake_taxonomy)
    monkeypatch.setattr(portfolio_ledger, "create_transaction", fake_create)
    monkeypatch.setattr(portfolio_ledger, "materialize_portfolio_nav", fake_materialize)

    async with _client() as ac:
        response = await ac.post(
            "/portfolios/7/transactions",
            json={
                "ticker": "vfiax",
                "side": "buy",
                "quantity": 1,
                "price": 450,
                "trade_date": "2026-01-01",
            },
        )

    assert response.status_code == 201, response.text
    assert ensure_calls == []
    assert materialized == [7]


async def test_create_transaction_route_maps_oversell_to_422(
    monkeypatch: pytest.MonkeyPatch, ensure_calls: list[list[str]]
) -> None:
    materialized: list[int] = []

    async def fake_exists(
        session: Any, portfolio_id: int, owner_sub: str | None = None
    ) -> bool:
        return True

    async def fake_fund_tickers(session: Any, tickers: Any) -> set[str]:
        return set()

    async def fake_create(session: Any, portfolio_id: int, payload: Any) -> None:
        raise portfolio_ledger.InsufficientPositionError("Cannot sell 2 AAPL")

    async def fake_materialize(session: Any, portfolio_id: int) -> None:
        materialized.append(portfolio_id)

    monkeypatch.setattr(portfolio_crud, "portfolio_exists", fake_exists)
    monkeypatch.setattr(portfolio_crud, "select_fund_tickers", fake_fund_tickers)
    monkeypatch.setattr(portfolio_ledger, "create_transaction", fake_create)
    monkeypatch.setattr(portfolio_ledger, "materialize_portfolio_nav", fake_materialize)

    async with _client() as ac:
        response = await ac.post(
            "/portfolios/7/transactions",
            json={
                "ticker": "AAPL",
                "side": "sell",
                "quantity": 2,
                "price": 100,
                "trade_date": "2026-01-01",
            },
        )

    assert response.status_code == 422
    assert "Cannot sell" in response.text
    assert ensure_calls == [["AAPL"]]
    assert materialized == []


async def test_nav_route_returns_transaction_aware_nav(
    monkeypatch: pytest.MonkeyPatch, ensure_calls: list[list[str]]
) -> None:
    d2 = dt.date(2026, 1, 2)
    d3 = dt.date(2026, 1, 3)

    async def fake_get_portfolio(
        session: Any, portfolio_id: int, owner_sub: str | None = None
    ) -> SimpleNamespace:
        return SimpleNamespace(id=portfolio_id, inception_date=dt.date(2025, 12, 31))

    async def fake_nav(
        session: Any, portfolio_id: int, *, end_date: dt.date | None = None
    ) -> list[SimpleNamespace]:
        assert end_date == d3
        return [
            SimpleNamespace(
                nav_date=dt.date(2025, 12, 31),
                nav=100.0,
                market_value=0.0,
                cash=0.0,
                total_value=0.0,
            ),
            SimpleNamespace(
                nav_date=d2,
                nav=110.0,
                market_value=1100.0,
                cash=-1000.0,
                total_value=100.0,
            ),
            SimpleNamespace(
                nav_date=d3,
                nav=120.0,
                market_value=600.0,
                cash=-400.0,
                total_value=200.0,
            ),
        ]

    monkeypatch.setattr(portfolio_crud, "get_portfolio", fake_get_portfolio)
    monkeypatch.setattr(portfolio_ledger, "list_materialized_nav", fake_nav)

    async with _client() as ac:
        response = await ac.get("/portfolios/7/nav?end_date=2026-01-03")

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["portfolio_id"] == 7
    assert body["inception_date"] == "2025-12-31"
    assert [p["date"] for p in body["points"]] == [
        "2025-12-31",
        "2026-01-02",
        "2026-01-03",
    ]
    assert [p["nav"] for p in body["points"]] == [100.0, 110.0, 120.0]
    assert body["points"][-1]["total_value"] == 200.0
    assert ensure_calls == []


async def test_nav_route_empty_ledger_returns_empty_series(
    monkeypatch: pytest.MonkeyPatch, ensure_calls: list[list[str]]
) -> None:
    async def fake_get_portfolio(
        session: Any, portfolio_id: int, owner_sub: str | None = None
    ) -> SimpleNamespace:
        return SimpleNamespace(id=portfolio_id, inception_date=dt.date(2025, 12, 31))

    async def fake_nav(
        session: Any, portfolio_id: int, *, end_date: dt.date | None = None
    ) -> list[Any]:
        return []

    monkeypatch.setattr(portfolio_crud, "get_portfolio", fake_get_portfolio)
    monkeypatch.setattr(portfolio_ledger, "list_materialized_nav", fake_nav)

    async with _client() as ac:
        response = await ac.get("/portfolios/7/nav")

    assert response.status_code == 200
    assert response.json() == {
        "portfolio_id": 7,
        "inception_date": "2025-12-31",
        "base_nav": 100.0,
        "points": [],
    }
    assert ensure_calls == []


async def test_materialize_portfolio_nav_rebuilds_daily_rows(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    d1 = dt.date(2026, 1, 1)
    d2 = dt.date(2026, 1, 2)
    added: list[Any] = []

    class FakeSession:
        async def execute(self, stmt: Any) -> None:
            return None

        def add_all(self, rows: list[Any]) -> None:
            added.extend(rows)

        async def flush(self) -> None:
            return None

    async def fake_get_portfolio(
        session: Any, portfolio_id: int, owner_sub: str | None = None
    ) -> SimpleNamespace:
        return SimpleNamespace(id=portfolio_id, inception_date=d1)

    async def fake_transactions(session: Any, portfolio_id: int) -> list[SimpleNamespace]:
        return [_tx("AAPL", "buy", 10, 100, d1)]

    async def fake_prices(
        session: Any, tickers: Any, start_date: dt.date, end_date: dt.date
    ) -> dict[str, list[tuple[dt.date, float]]]:
        assert tickers == ["AAPL"]
        assert start_date == d1
        assert end_date == d2
        return {"AAPL": [(d1, 100), (d2, 110)]}

    monkeypatch.setattr(portfolio_crud, "get_portfolio", fake_get_portfolio)
    monkeypatch.setattr(portfolio_ledger, "list_transactions", fake_transactions)
    monkeypatch.setattr(portfolio_ledger, "load_price_history", fake_prices)

    result = await portfolio_ledger.materialize_portfolio_nav(
        FakeSession(), 7, end_date=d2
    )

    assert result == portfolio_ledger.PortfolioNavMaterialization(7, 2, d1, d2)
    assert [(row.nav_date, row.nav, row.market_value, row.total_value) for row in added] == [
        (d1, 100.0, 1000.0, 0.0),
        (d2, 110.0, 1100.0, 100.0),
    ]
