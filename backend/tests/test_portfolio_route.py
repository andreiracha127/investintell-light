"""Tests for POST /portfolio/analysis.

The ingestion service and DB read helpers are stubbed at the route-module
boundary; the Tiingo client and DB session dependencies are overridden.
No live network, no live DB.
"""

import datetime as dt
from collections.abc import AsyncGenerator
from typing import Any

import numpy as np
import pandas as pd
import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from app.api.routes import portfolio, stocks
from app.core.db import get_session
from app.core.tiingo_provider import get_tiingo_client
from app.ingestion.service import EnsureReport
from app.main import create_app
from app.tiingo.exceptions import TiingoNotFoundError

N_DAYS = 420

AdjCloseRow = tuple[dt.date, float]


def _synthetic_rows(seed: int, n_days: int = N_DAYS) -> list[AdjCloseRow]:
    """~n_days business days of adjusted closes ending near today, deterministic."""
    dates = pd.bdate_range(end=dt.date.today(), periods=n_days)
    rng = np.random.default_rng(seed)
    closes = 100.0 * np.cumprod(1 + rng.normal(0.0004, 0.01, n_days))
    return [(ts.date(), float(c)) for ts, c in zip(dates, closes, strict=True)]


ROWS_BY_TICKER: dict[str, list[AdjCloseRow]] = {
    "AAPL": _synthetic_rows(seed=1),
    "MSFT": _synthetic_rows(seed=2),
    "SPY": _synthetic_rows(seed=3),
}

WEIGHTS_BODY: dict[str, Any] = {
    "positions": [
        {"ticker": "AAPL", "weight": 0.6},
        {"ticker": "MSFT", "weight": 0.4},
    ],
    "mode": "weights",
    "range": "1Y",
}


def _app_with_overrides() -> FastAPI:
    app = create_app()
    app.dependency_overrides[get_session] = lambda: None
    app.dependency_overrides[get_tiingo_client] = lambda: object()
    return app


def _install_stubs(
    monkeypatch: pytest.MonkeyPatch,
    rows_by_ticker: dict[str, list[AdjCloseRow]] | None = None,
) -> None:
    rows_map = ROWS_BY_TICKER if rows_by_ticker is None else rows_by_ticker

    async def fake_ensure(*args: Any, **kwargs: Any) -> EnsureReport:
        return EnsureReport()

    async def fake_bounds(
        session: Any, ticker: str
    ) -> tuple[dt.date | None, dt.date | None]:
        rows = rows_map.get(ticker, [])
        if not rows:
            return None, None
        return rows[0][0], rows[-1][0]

    async def fake_adj_close(
        session: Any, ticker: str, start: dt.date, end: dt.date
    ) -> list[AdjCloseRow]:
        return [r for r in rows_map.get(ticker, []) if start <= r[0] <= end]

    # _ensure_eod_or_http_error lives in the stocks module and calls the
    # stocks-module global ensure_eod_data; the read helpers are looked up as
    # portfolio-module globals.
    monkeypatch.setattr(stocks, "ensure_eod_data", fake_ensure)
    monkeypatch.setattr(portfolio, "_select_date_bounds", fake_bounds)
    monkeypatch.setattr(portfolio, "_select_adj_close_rows", fake_adj_close)


@pytest.fixture
async def stub_client(monkeypatch: pytest.MonkeyPatch) -> AsyncGenerator[AsyncClient, None]:
    _install_stubs(monkeypatch)
    transport = ASGITransport(app=_app_with_overrides())
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


# ---------------------------------------------------------------------------
# Happy paths
# ---------------------------------------------------------------------------


async def test_weights_mode_happy_path_shape(stub_client: AsyncClient) -> None:
    response = await stub_client.post("/portfolio/analysis", json=WEIGHTS_BODY)
    assert response.status_code == 200
    body = response.json()
    assert set(body) == {
        "params",
        "allocation",
        "nav",
        "benchmark_comparison",
        "stats",
        "correlation_matrix",
        "risk_contributions",
        "histogram",
    }
    assert body["params"]["mode"] == "weights"
    assert body["params"]["range"] == "1Y"
    assert body["params"]["benchmark"] == "SPY"
    assert body["params"]["initial_nav"] == pytest.approx(10_000.0)

    weights = {p["ticker"]: p["weight"] for p in body["allocation"]["positions"]}
    assert weights["AAPL"] == pytest.approx(0.6)
    assert weights["MSFT"] == pytest.approx(0.4)

    # NAV points serialize as [iso_date, value] pairs starting at initial_nav.
    first_point = body["nav"][0]
    assert dt.date.fromisoformat(first_point[0])
    assert first_point[1] == pytest.approx(10_000.0)

    assert set(body["benchmark_comparison"]) == {"portfolio", "benchmark"}
    assert body["benchmark_comparison"]["portfolio"][0][1] == 0.0

    assert body["correlation_matrix"]["tickers"] == ["AAPL", "MSFT"]
    assert len(body["correlation_matrix"]["matrix"]) == 2

    contributions = [rc["contribution"] for rc in body["risk_contributions"]]
    assert sum(contributions) == pytest.approx(1.0)

    assert body["stats"]["var_99"] >= body["stats"]["var_95"]
    assert body["stats"]["diversification_ratio"] >= 1.0
    assert len(body["histogram"]["counts"]) == 20


async def test_quantities_mode_happy_path(stub_client: AsyncClient) -> None:
    response = await stub_client.post(
        "/portfolio/analysis",
        json={
            "positions": [
                {"ticker": "AAPL", "quantity": 10},
                {"ticker": "MSFT", "quantity": 5},
            ],
            "mode": "quantities",
        },
    )
    assert response.status_code == 200
    body = response.json()
    assert body["params"]["mode"] == "quantities"
    weights = [p["weight"] for p in body["allocation"]["positions"]]
    assert sum(weights) == pytest.approx(1.0)
    assert body["params"]["initial_nav"] == pytest.approx(
        body["allocation"]["initial_nav"]
    )
    assert body["nav"][0][1] == pytest.approx(body["params"]["initial_nav"])


async def test_benchmark_may_coincide_with_a_position(stub_client: AsyncClient) -> None:
    response = await stub_client.post(
        "/portfolio/analysis",
        json={
            "positions": [
                {"ticker": "AAPL", "weight": 0.5},
                {"ticker": "SPY", "weight": 0.5},
            ],
            "mode": "weights",
            "benchmark": "SPY",
        },
    )
    assert response.status_code == 200
    assert response.json()["params"]["benchmark"] == "SPY"


async def test_tickers_are_uppercase_normalized(stub_client: AsyncClient) -> None:
    response = await stub_client.post(
        "/portfolio/analysis",
        json={
            "positions": [
                {"ticker": "aapl", "weight": 0.6},
                {"ticker": " msft ", "weight": 0.4},
            ],
            "mode": "weights",
        },
    )
    assert response.status_code == 200
    tickers = [p["ticker"] for p in response.json()["allocation"]["positions"]]
    assert tickers == ["AAPL", "MSFT"]


# ---------------------------------------------------------------------------
# Validation (422) paths
# ---------------------------------------------------------------------------


async def test_single_position_is_rejected(stub_client: AsyncClient) -> None:
    response = await stub_client.post(
        "/portfolio/analysis",
        json={"positions": [{"ticker": "AAPL", "weight": 1.0}], "mode": "weights"},
    )
    assert response.status_code == 422


async def test_fifty_one_positions_are_rejected(stub_client: AsyncClient) -> None:
    positions = [{"ticker": f"T{i}", "weight": 1.0 / 51} for i in range(51)]
    response = await stub_client.post(
        "/portfolio/analysis", json={"positions": positions, "mode": "weights"}
    )
    assert response.status_code == 422


async def test_weights_sum_off_tolerance_reports_actual_sum(
    stub_client: AsyncClient,
) -> None:
    response = await stub_client.post(
        "/portfolio/analysis",
        json={
            "positions": [
                {"ticker": "AAPL", "weight": 0.55},
                {"ticker": "MSFT", "weight": 0.4},
            ],
            "mode": "weights",
        },
    )
    assert response.status_code == 422
    assert "0.95" in str(response.json()["detail"])


async def test_duplicate_ticker_is_rejected(stub_client: AsyncClient) -> None:
    response = await stub_client.post(
        "/portfolio/analysis",
        json={
            "positions": [
                {"ticker": "AAPL", "weight": 0.5},
                {"ticker": "aapl", "weight": 0.5},
            ],
            "mode": "weights",
        },
    )
    assert response.status_code == 422
    assert "Duplicate" in str(response.json()["detail"])


async def test_weights_mode_rejects_quantity_field(stub_client: AsyncClient) -> None:
    response = await stub_client.post(
        "/portfolio/analysis",
        json={
            "positions": [
                {"ticker": "AAPL", "weight": 0.5},
                {"ticker": "MSFT", "quantity": 10},
            ],
            "mode": "weights",
        },
    )
    assert response.status_code == 422
    assert "weight" in str(response.json()["detail"])


async def test_quantities_mode_rejects_nonpositive_quantity(
    stub_client: AsyncClient,
) -> None:
    response = await stub_client.post(
        "/portfolio/analysis",
        json={
            "positions": [
                {"ticker": "AAPL", "quantity": 10},
                {"ticker": "MSFT", "quantity": 0},
            ],
            "mode": "quantities",
        },
    )
    assert response.status_code == 422
    assert "MSFT" in str(response.json()["detail"])


async def test_invalid_ticker_format_is_rejected(stub_client: AsyncClient) -> None:
    response = await stub_client.post(
        "/portfolio/analysis",
        json={
            "positions": [
                {"ticker": "WAY_TOO_LONG_TICKER", "weight": 0.5},
                {"ticker": "MSFT", "weight": 0.5},
            ],
            "mode": "weights",
        },
    )
    assert response.status_code == 422


# ---------------------------------------------------------------------------
# Data error paths
# ---------------------------------------------------------------------------


async def test_unknown_ticker_returns_404(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_ensure(*args: Any, **kwargs: Any) -> EnsureReport:
        raise TiingoNotFoundError("nope")

    monkeypatch.setattr(stocks, "ensure_eod_data", fake_ensure)
    transport = ASGITransport(app=_app_with_overrides())
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        response = await ac.post("/portfolio/analysis", json=WEIGHTS_BODY)
    assert response.status_code == 404


async def test_ticker_without_rows_returns_404(monkeypatch: pytest.MonkeyPatch) -> None:
    rows = dict(ROWS_BY_TICKER)
    rows["MSFT"] = []
    _install_stubs(monkeypatch, rows_by_ticker=rows)
    transport = ASGITransport(app=_app_with_overrides())
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        response = await ac.post("/portfolio/analysis", json=WEIGHTS_BODY)
    assert response.status_code == 404
    assert "MSFT" in response.json()["detail"]


async def test_insufficient_common_history_returns_422_naming_ticker(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    rows = dict(ROWS_BY_TICKER)
    rows["MSFT"] = _synthetic_rows(seed=2, n_days=5)
    _install_stubs(monkeypatch, rows_by_ticker=rows)
    transport = ASGITransport(app=_app_with_overrides())
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        response = await ac.post("/portfolio/analysis", json=WEIGHTS_BODY)
    assert response.status_code == 422
    assert "MSFT" in response.json()["detail"]
