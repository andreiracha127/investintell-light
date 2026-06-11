"""Tests for the /statistics/* routes (F5).

The ingestion service, DB reads and portfolio loading are stubbed at the
service-module boundary; the Tiingo client and DB session dependencies are
overridden. No live network, no live DB (same approach as the F3.2 tests).
"""

import datetime as dt
from collections.abc import AsyncGenerator
from types import SimpleNamespace
from typing import Any

import numpy as np
import pandas as pd
import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from app.api import _shared as api_shared
from app.core.db import get_session
from app.core.tiingo_provider import get_tiingo_client
from app.ingestion.service import EnsureReport
from app.main import create_app
from app.services import statistics as statistics_service
from app.tiingo.exceptions import TiingoNotFoundError

N_DAYS = 420

AdjCloseRow = tuple[dt.date, float]


def _synthetic_rows(seed: int, n_days: int = N_DAYS) -> list[AdjCloseRow]:
    dates = pd.bdate_range(end=dt.date.today(), periods=n_days)
    rng = np.random.default_rng(seed)
    closes = 100.0 * np.cumprod(1 + rng.normal(0.0004, 0.01, n_days))
    return [(ts.date(), float(c)) for ts, c in zip(dates, closes, strict=True)]


ROWS_BY_TICKER: dict[str, list[AdjCloseRow]] = {
    "AAPL": _synthetic_rows(seed=1),
    "MSFT": _synthetic_rows(seed=2),
    "SPY": _synthetic_rows(seed=3),
}

PORTFOLIO = SimpleNamespace(
    id=7,
    name="Temp F5",
    cash=1000.0,
    positions=[
        SimpleNamespace(ticker="AAPL", quantity=10.0),
        SimpleNamespace(ticker="MSFT", quantity=5.0),
    ],
)

START = (dt.date.today() - dt.timedelta(days=365)).isoformat()
END = dt.date.today().isoformat()


def _app_with_overrides() -> FastAPI:
    app = create_app()
    app.dependency_overrides[get_session] = lambda: None
    app.dependency_overrides[get_tiingo_client] = lambda: object()
    return app


def _install_stubs(
    monkeypatch: pytest.MonkeyPatch,
    rows_by_ticker: dict[str, list[AdjCloseRow]] | None = None,
    portfolio: Any | None = PORTFOLIO,
) -> None:
    rows_map = ROWS_BY_TICKER if rows_by_ticker is None else rows_by_ticker

    async def fake_ensure(*args: Any, **kwargs: Any) -> EnsureReport:
        return EnsureReport()

    async def fake_adj_close(
        session: Any, ticker: str, start: dt.date, end: dt.date
    ) -> list[AdjCloseRow]:
        return [r for r in rows_map.get(ticker, []) if start <= r[0] <= end]

    async def fake_get_portfolio(session: Any, portfolio_id: int) -> Any | None:
        if portfolio is not None and portfolio_id == portfolio.id:
            return portfolio
        return None

    monkeypatch.setattr(api_shared, "ensure_eod_data", fake_ensure)
    monkeypatch.setattr(statistics_service, "_select_adj_close_rows", fake_adj_close)
    monkeypatch.setattr(
        statistics_service.portfolio_crud, "get_portfolio", fake_get_portfolio
    )


@pytest.fixture
async def stub_client(
    monkeypatch: pytest.MonkeyPatch,
) -> AsyncGenerator[AsyncClient, None]:
    _install_stubs(monkeypatch)
    transport = ASGITransport(app=_app_with_overrides())
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


# ---------------------------------------------------------------------------
# /statistics/scenario
# ---------------------------------------------------------------------------


async def test_scenario_happy_path_shape(stub_client: AsyncClient) -> None:
    response = await stub_client.post(
        "/statistics/scenario",
        json={"portfolio_id": 7, "start_date": START, "end_date": END},
    )
    assert response.status_code == 200
    body = response.json()
    assert set(body) == {
        "params",
        "nav_cash",
        "weights_percent",
        "asset_performance",
        "histogram",
        "statistics",
    }
    assert body["params"]["portfolio_id"] == 7
    assert body["params"]["name"] == "Temp F5"
    assert body["params"]["frequency"] == "daily"

    nav_tickers = [s["ticker"] for s in body["nav_cash"]]
    assert nav_tickers == ["AAPL", "MSFT", "CASH", "TOTAL"]
    # Points serialize as [iso_date, value] pairs.
    first_point = body["nav_cash"][0]["points"][0]
    assert dt.date.fromisoformat(first_point[0])
    assert isinstance(first_point[1], float)

    assert [s["ticker"] for s in body["weights_percent"]] == ["AAPL", "MSFT", "CASH"]
    assert [s["ticker"] for s in body["asset_performance"]] == ["AAPL", "MSFT", "TOTAL"]

    stats = body["statistics"]
    assert set(stats) == {
        "start_date",
        "end_date",
        "start_nav",
        "end_nav",
        "max_nav",
        "min_nav",
        "max_return",
        "min_return",
        "annualized_volatility",
        "var_95",
        "var_99",
    }
    assert stats["var_99"] >= stats["var_95"]
    assert len(body["histogram"]["counts"]) == 20


async def test_scenario_unknown_portfolio_returns_404(stub_client: AsyncClient) -> None:
    response = await stub_client.post(
        "/statistics/scenario",
        json={"portfolio_id": 99, "start_date": START, "end_date": END},
    )
    assert response.status_code == 404


async def test_scenario_empty_portfolio_returns_422(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    empty = SimpleNamespace(id=7, name="Empty", cash=0.0, positions=[])
    _install_stubs(monkeypatch, portfolio=empty)
    transport = ASGITransport(app=_app_with_overrides())
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        response = await ac.post(
            "/statistics/scenario",
            json={"portfolio_id": 7, "start_date": START, "end_date": END},
        )
    assert response.status_code == 422
    assert "no positions" in response.json()["detail"]


async def test_scenario_inverted_dates_return_422(stub_client: AsyncClient) -> None:
    response = await stub_client.post(
        "/statistics/scenario",
        json={"portfolio_id": 7, "start_date": END, "end_date": START},
    )
    assert response.status_code == 422


async def test_scenario_short_window_returns_422_naming_ticker(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    rows = dict(ROWS_BY_TICKER)
    rows["MSFT"] = _synthetic_rows(seed=2, n_days=5)
    _install_stubs(monkeypatch, rows_by_ticker=rows)
    transport = ASGITransport(app=_app_with_overrides())
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        response = await ac.post(
            "/statistics/scenario",
            json={"portfolio_id": 7, "start_date": START, "end_date": END},
        )
    assert response.status_code == 422
    assert "MSFT" in response.json()["detail"]


# ---------------------------------------------------------------------------
# /statistics/beta
# ---------------------------------------------------------------------------


async def test_beta_ticker_vs_portfolio(stub_client: AsyncClient) -> None:
    response = await stub_client.post(
        "/statistics/beta",
        json={
            "asset_x": {"kind": "ticker", "ticker": "SPY"},
            "asset_y": {"kind": "portfolio", "id": 7},
            "start_date": START,
            "end_date": END,
        },
    )
    assert response.status_code == 200
    body = response.json()
    assert set(body) == {"labels", "scatter", "regression", "regression_line"}
    assert body["labels"] == {"x": "SPY", "y": "Temp F5"}
    regression = body["regression"]
    assert regression["n_points"] == len(body["scatter"])
    assert -1.0 <= regression["r"] <= 1.0
    assert len(body["regression_line"]) == 2
    # Scatter points are [ret_x, ret_y] float pairs.
    assert len(body["scatter"][0]) == 2


async def test_beta_unknown_ticker_returns_404(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_ensure(*args: Any, **kwargs: Any) -> EnsureReport:
        raise TiingoNotFoundError("nope")

    _install_stubs(monkeypatch)
    monkeypatch.setattr(api_shared, "ensure_eod_data", fake_ensure)
    transport = ASGITransport(app=_app_with_overrides())
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        response = await ac.post(
            "/statistics/beta",
            json={
                "asset_x": {"kind": "ticker", "ticker": "NOPE"},
                "asset_y": {"kind": "ticker", "ticker": "SPY"},
                "start_date": START,
                "end_date": END,
            },
        )
    assert response.status_code == 404


async def test_beta_malformed_asset_ref_returns_422(stub_client: AsyncClient) -> None:
    response = await stub_client.post(
        "/statistics/beta",
        json={
            "asset_x": {"kind": "index", "ticker": "SPX"},
            "asset_y": {"kind": "ticker", "ticker": "SPY"},
            "start_date": START,
            "end_date": END,
        },
    )
    assert response.status_code == 422


# ---------------------------------------------------------------------------
# /statistics/correlation
# ---------------------------------------------------------------------------


async def test_correlation_ticker_vs_portfolio(stub_client: AsyncClient) -> None:
    response = await stub_client.post(
        "/statistics/correlation",
        json={
            "asset_x": {"kind": "ticker", "ticker": "SPY"},
            "asset_y": {"kind": "portfolio", "id": 7},
            "start_date": (dt.date.today() - dt.timedelta(days=180)).isoformat(),
            "end_date": END,
            "window": 63,
        },
    )
    assert response.status_code == 200
    body = response.json()
    assert set(body) == {"labels", "window", "series", "current"}
    assert body["window"] == 63
    assert -1.0 <= body["current"] <= 1.0
    assert body["current"] == body["series"][-1][1]
    for _, value in body["series"]:
        assert -1.0 <= value <= 1.0


@pytest.mark.parametrize("window", [5, 300])
async def test_correlation_window_out_of_bounds_returns_422(
    stub_client: AsyncClient, window: int
) -> None:
    response = await stub_client.post(
        "/statistics/correlation",
        json={
            "asset_x": {"kind": "ticker", "ticker": "SPY"},
            "asset_y": {"kind": "ticker", "ticker": "AAPL"},
            "start_date": START,
            "end_date": END,
            "window": window,
        },
    )
    assert response.status_code == 422


# ---------------------------------------------------------------------------
# /statistics/stock-correlation
# ---------------------------------------------------------------------------


async def test_stock_correlation_happy_path(stub_client: AsyncClient) -> None:
    response = await stub_client.post(
        "/statistics/stock-correlation", json={"portfolio_id": 7, "window": 63}
    )
    assert response.status_code == 200
    body = response.json()
    assert set(body) == {"tickers", "matrix", "window", "as_of"}
    assert body["tickers"] == ["AAPL", "MSFT"]
    assert body["window"] == 63
    matrix = body["matrix"]
    assert len(matrix) == 2 and all(len(row) == 2 for row in matrix)
    assert matrix[0][0] == 1.0 and matrix[1][1] == 1.0
    assert matrix[0][1] == pytest.approx(matrix[1][0])
    assert dt.date.fromisoformat(body["as_of"])


async def test_stock_correlation_unknown_portfolio_returns_404(
    stub_client: AsyncClient,
) -> None:
    response = await stub_client.post(
        "/statistics/stock-correlation", json={"portfolio_id": 99}
    )
    assert response.status_code == 404


async def test_stock_correlation_short_history_returns_422_naming_ticker(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    rows = dict(ROWS_BY_TICKER)
    rows["MSFT"] = _synthetic_rows(seed=2, n_days=20)
    _install_stubs(monkeypatch, rows_by_ticker=rows)
    transport = ASGITransport(app=_app_with_overrides())
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        response = await ac.post(
            "/statistics/stock-correlation", json={"portfolio_id": 7, "window": 63}
        )
    assert response.status_code == 422
    assert "MSFT" in response.json()["detail"]
