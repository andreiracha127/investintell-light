"""Tests for GET /portfolios/{id}/overview and the pure overview math.

DB reads and the EOD ensure are stubbed; ``build_overview`` runs for real so
the route tests exercise the actual P&L math. No live network, no live DB.
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
from app.services.portfolio_crud import MissingPriceDataError, build_overview

_CREATED = dt.datetime(2026, 6, 10, 12, 0, tzinfo=dt.UTC)
_LAST = dt.date(2026, 6, 10)
_PREV = dt.date(2026, 6, 9)

ClosesMap = dict[str, list[tuple[dt.date, float]]]


def _position(
    ticker: str,
    quantity: float,
    acq_price: float | None,
    basis: str = "reference",
    commission: float | None = None,
    trade_date: dt.date | None = None,
) -> SimpleNamespace:
    return SimpleNamespace(
        ticker=ticker,
        quantity=quantity,
        acq_price=acq_price,
        basis=basis,
        commission=commission,
        trade_date=trade_date,
    )


def _portfolio(positions: list[SimpleNamespace], cash: float = 0.0) -> SimpleNamespace:
    return SimpleNamespace(
        id=1,
        name="Test",
        cash=cash,
        created_at=_CREATED,
        updated_at=_CREATED,
        positions=positions,
    )


def _client() -> AsyncClient:
    app = create_app()
    app.dependency_overrides[get_session] = lambda: None
    app.dependency_overrides[get_tiingo_client] = lambda: object()
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


def _install_stubs(
    monkeypatch: pytest.MonkeyPatch,
    portfolio: SimpleNamespace | None,
    closes: ClosesMap,
    names: dict[str, str | None] | None = None,
    fund_tickers: set[str] | None = None,
    navs: ClosesMap | None = None,
    fund_names: dict[str, str | None] | None = None,
) -> list[list[str]]:
    ensure_calls: list[list[str]] = []

    async def fake_ensure(
        session: Any, client: Any, tickers: list[str], start: Any, end: Any, **kw: Any
    ) -> EnsureReport:
        ensure_calls.append(list(tickers))
        return EnsureReport()

    async def fake_get(session: Any, portfolio_id: int) -> SimpleNamespace | None:
        return portfolio

    async def fake_closes(session: Any, tickers: Any) -> ClosesMap:
        return closes

    async def fake_names(session: Any, tickers: Any) -> dict[str, str | None]:
        return names or {}

    async def fake_fund_tickers(session: Any, tickers: Any) -> set[str]:
        return (fund_tickers or set()) & set(tickers)

    async def fake_eod_known(session: Any, tickers: Any) -> set[str]:
        return set(closes) & set(tickers)

    async def fake_navs(session: Any, tickers: Any) -> ClosesMap:
        return {t: rows for t, rows in (navs or {}).items() if t in set(tickers)}

    async def fake_fund_names(session: Any, tickers: Any) -> dict[str, str | None]:
        return fund_names or {}

    monkeypatch.setattr(api_shared, "ensure_eod_data", fake_ensure)
    monkeypatch.setattr(portfolio_crud, "get_portfolio", fake_get)
    monkeypatch.setattr(portfolio_crud, "select_last_two_closes", fake_closes)
    monkeypatch.setattr(portfolio_crud, "select_instrument_names", fake_names)
    monkeypatch.setattr(portfolio_crud, "select_fund_tickers", fake_fund_tickers)
    monkeypatch.setattr(portfolio_crud, "select_tickers_with_eod", fake_eod_known)
    monkeypatch.setattr(portfolio_crud, "select_last_two_navs", fake_navs)
    monkeypatch.setattr(portfolio_crud, "select_fund_names", fake_fund_names)
    return ensure_calls


# ---------------------------------------------------------------------------
# Route: P&L math (acq 100, last 110, qty 2 -> pnl 20, pnl_pct 0.10)
# ---------------------------------------------------------------------------


async def test_overview_pnl_math(monkeypatch: pytest.MonkeyPatch) -> None:
    ensure_calls = _install_stubs(
        monkeypatch,
        _portfolio([_position("AAPL", 2.0, 100.0)]),
        closes={"AAPL": [(_LAST, 110.0), (_PREV, 105.0)]},
        names={"AAPL": "Apple Inc"},
    )
    async with _client() as ac:
        response = await ac.get("/portfolios/1/overview")

    assert response.status_code == 200
    body = response.json()
    assert ensure_calls == [["AAPL"]]  # staleness refresh ran first
    (row,) = body["positions"]
    assert row["ticker"] == "AAPL"
    assert row["name"] == "Apple Inc"
    assert row["last_close"] == 110.0
    assert row["prev_close"] == 105.0
    assert row["change"] == pytest.approx(5.0)
    assert row["change_pct"] == pytest.approx(5.0 / 105.0)
    assert row["market_value"] == pytest.approx(220.0)
    assert row["cost_basis"] == pytest.approx(200.0)
    assert row["pnl"] == pytest.approx(20.0)
    assert row["pnl_pct"] == pytest.approx(0.10)
    assert row["as_of"] == _LAST.isoformat()


async def test_overview_null_acq_price_nulls_pnl_and_aggregates_skip(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_stubs(
        monkeypatch,
        _portfolio(
            [_position("AAPL", 2.0, 100.0), _position("MSFT", 5.0, None)],
            cash=50.0,
        ),
        closes={
            "AAPL": [(_LAST, 110.0), (_PREV, 105.0)],
            "MSFT": [(_LAST, 40.0), (_PREV, 41.0)],
        },
    )
    async with _client() as ac:
        response = await ac.get("/portfolios/1/overview")

    assert response.status_code == 200
    body = response.json()
    msft = body["positions"][1]
    assert msft["acq_price"] is None
    assert msft["cost_basis"] is None
    assert msft["pnl"] is None
    assert msft["pnl_pct"] is None
    assert msft["market_value"] == pytest.approx(200.0)
    assert msft["change"] == pytest.approx(-1.0)

    agg = body["aggregates"]
    assert agg["total_market_value"] == pytest.approx(420.0)  # 220 + 200
    # Only AAPL carries a cost basis — MSFT is skipped, NOT treated as zero.
    assert agg["total_cost_basis"] == pytest.approx(200.0)
    assert agg["total_pnl"] == pytest.approx(20.0)
    assert agg["total_pnl_pct"] == pytest.approx(0.10)
    assert agg["cash"] == 50.0
    assert agg["total_value"] == pytest.approx(470.0)
    assert agg["as_of"] == _LAST.isoformat()


async def test_overview_all_null_acq_prices_null_all_pnl_aggregates(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_stubs(
        monkeypatch,
        _portfolio([_position("MSFT", 5.0, None)]),
        closes={"MSFT": [(_LAST, 40.0)]},
    )
    async with _client() as ac:
        response = await ac.get("/portfolios/1/overview")

    agg = response.json()["aggregates"]
    assert agg["total_cost_basis"] is None
    assert agg["total_pnl"] is None
    assert agg["total_pnl_pct"] is None
    assert agg["total_market_value"] == pytest.approx(200.0)


async def test_overview_single_close_row_nulls_change(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_stubs(
        monkeypatch,
        _portfolio([_position("IPO", 1.0, 10.0)]),
        closes={"IPO": [(_LAST, 12.0)]},
    )
    async with _client() as ac:
        response = await ac.get("/portfolios/1/overview")

    (row,) = response.json()["positions"]
    assert row["prev_close"] is None
    assert row["change"] is None
    assert row["change_pct"] is None
    assert row["last_close"] == 12.0


async def test_overview_empty_portfolio_zeroed_null_aggregates_no_ensure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ensure_calls = _install_stubs(monkeypatch, _portfolio([], cash=123.0), closes={})
    async with _client() as ac:
        response = await ac.get("/portfolios/1/overview")

    assert response.status_code == 200
    body = response.json()
    assert body["positions"] == []
    assert body["aggregates"] == {
        "total_market_value": 0.0,
        "total_cost_basis": None,
        "total_pnl": None,
        "total_pnl_pct": None,
        "cash": 123.0,
        "total_value": 123.0,
        "as_of": None,
    }
    assert ensure_calls == []  # nothing to refresh


async def test_overview_fund_position_priced_via_nav(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A fund position (no eod_prices rows) is priced from fund_nav: latest
    NAV = last, second-latest = prev; Tiingo is never consulted for it."""
    ensure_calls = _install_stubs(
        monkeypatch,
        _portfolio(
            [_position("AAPL", 2.0, 100.0), _position("VFIAX", 10.0, 440.0)],
        ),
        closes={"AAPL": [(_LAST, 110.0), (_PREV, 105.0)]},
        names={"AAPL": "Apple Inc"},
        fund_tickers={"VFIAX"},
        navs={"VFIAX": [(_LAST, 450.0), (_PREV, 445.0)]},
        fund_names={"VFIAX": "Vanguard 500 Index Admiral"},
    )
    async with _client() as ac:
        response = await ac.get("/portfolios/1/overview")

    assert response.status_code == 200, response.text
    body = response.json()
    # Only the equity is refreshed via Tiingo — the fund ticker is skipped.
    assert ensure_calls == [["AAPL"]]
    fund_row = next(r for r in body["positions"] if r["ticker"] == "VFIAX")
    assert fund_row["name"] == "Vanguard 500 Index Admiral"
    assert fund_row["last_close"] == 450.0
    assert fund_row["prev_close"] == 445.0
    assert fund_row["change"] == pytest.approx(5.0)
    assert fund_row["change_pct"] == pytest.approx(5.0 / 445.0)
    assert fund_row["market_value"] == pytest.approx(4500.0)
    assert fund_row["pnl"] == pytest.approx(100.0)  # (450 - 440) * 10
    assert body["aggregates"]["total_market_value"] == pytest.approx(220.0 + 4500.0)


async def test_overview_fund_only_portfolio_skips_ensure_entirely(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ensure_calls = _install_stubs(
        monkeypatch,
        _portfolio([_position("VFIAX", 1.0, None)]),
        closes={},
        fund_tickers={"VFIAX"},
        navs={"VFIAX": [(_LAST, 450.0)]},
    )
    async with _client() as ac:
        response = await ac.get("/portfolios/1/overview")

    assert response.status_code == 200, response.text
    assert ensure_calls == []
    (row,) = response.json()["positions"]
    assert row["last_close"] == 450.0
    assert row["prev_close"] is None


async def test_overview_missing_portfolio_404(monkeypatch: pytest.MonkeyPatch) -> None:
    _install_stubs(monkeypatch, None, closes={})
    async with _client() as ac:
        response = await ac.get("/portfolios/999/overview")

    assert response.status_code == 404


async def test_overview_ticker_without_price_rows_404(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_stubs(
        monkeypatch,
        _portfolio([_position("GHOST", 1.0, None)]),
        closes={},  # ensure "succeeded" but no rows came back — fail loud
    )
    async with _client() as ac:
        response = await ac.get("/portfolios/1/overview")

    assert response.status_code == 404
    assert "No price data available for GHOST" in response.json()["detail"]


# ---------------------------------------------------------------------------
# F8.6b: class-ticker pricing (series-NAV proxy) + basis fields in the payload
# ---------------------------------------------------------------------------


async def test_overview_class_ticker_priced_via_series_nav_proxy(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A share-class ticker (fund_classes) is a fund ticker: skipped by the
    Tiingo ensure, priced from the SERIES NAV (proxy) and displayed as
    'Fund — Class'. Executed fill fields surface on the overview row."""
    ensure_calls = _install_stubs(
        monkeypatch,
        _portfolio(
            [
                _position(
                    "RGAGX", 10.0, 100.5,
                    basis="executed", commission=5.0,
                    trade_date=dt.date(2026, 6, 10),
                )
            ]
        ),
        closes={},
        fund_tickers={"RGAGX"},
        navs={"RGAGX": [(_LAST, 80.0), (_PREV, 79.0)]},
        fund_names={"RGAGX": "Growth Fund of America — Class R-6"},
    )
    async with _client() as ac:
        response = await ac.get("/portfolios/1/overview")

    assert response.status_code == 200
    assert ensure_calls == []  # class ticker — Tiingo never consulted
    (row,) = response.json()["positions"]
    assert row["name"] == "Growth Fund of America — Class R-6"
    assert row["last_close"] == 80.0  # series NAV proxies the class NAV
    assert row["basis"] == "executed"
    assert row["commission"] == 5.0
    assert row["trade_date"] == "2026-06-10"
    assert row["acq_price"] == 100.5  # effective cost basis incl. commission
    assert row["market_value"] == pytest.approx(800.0)


async def test_overview_reference_position_basis_fields(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_stubs(
        monkeypatch,
        _portfolio([_position("AAPL", 2.0, 100.0)]),
        closes={"AAPL": [(_LAST, 110.0)]},
    )
    async with _client() as ac:
        response = await ac.get("/portfolios/1/overview")

    (row,) = response.json()["positions"]
    assert row["basis"] == "reference"
    assert row["commission"] is None
    assert row["trade_date"] is None


# ---------------------------------------------------------------------------
# Pure math (build_overview directly)
# ---------------------------------------------------------------------------


def test_build_overview_missing_closes_raises() -> None:
    with pytest.raises(MissingPriceDataError):
        build_overview(
            [_position("AAPL", 1.0, None)], closes_by_ticker={}, names_by_ticker={}, cash=0.0
        )


def test_build_overview_as_of_is_max_across_positions() -> None:
    older = dt.date(2026, 6, 5)
    rows, aggregates = build_overview(
        [_position("A", 1.0, None), _position("B", 1.0, None)],
        closes_by_ticker={"A": [(older, 1.0)], "B": [(_LAST, 2.0)]},
        names_by_ticker={},
        cash=0.0,
    )
    assert rows[0].as_of == older
    assert rows[1].as_of == _LAST
    assert aggregates.as_of == _LAST
