"""Tests for POST /portfolio/analysis.

DB read helpers are stubbed at the route-module boundary. Historical EOD data
is DB-only: no live network, no live DB.
"""

import datetime as dt
from collections.abc import AsyncGenerator
from typing import Any

import numpy as np
import pandas as pd
import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from app.api.routes import portfolio
from app.core.db import get_session
from app.main import create_app

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
    return app


def _install_stubs(
    monkeypatch: pytest.MonkeyPatch,
    rows_by_ticker: dict[str, list[AdjCloseRow]] | None = None,
) -> None:
    rows_map = ROWS_BY_TICKER if rows_by_ticker is None else rows_by_ticker

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

    # The read helpers are looked up as portfolio-module globals (aliases to the
    # canonical implementations in app.services._series).
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


async def test_max_range_weekly_bounding_applies_to_both_comparison_series(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """MAX range: comparison.portfolio AND comparison.benchmark are weekly (W-FRI).

    Both series must contain only Friday dates and have the same length —
    the weekly bounding must be applied symmetrically to both.
    """
    _install_stubs(monkeypatch)
    transport = ASGITransport(app=_app_with_overrides())
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        response = await ac.post(
            "/portfolio/analysis",
            json={
                "positions": [
                    {"ticker": "AAPL", "weight": 0.6},
                    {"ticker": "MSFT", "weight": 0.4},
                ],
                "mode": "weights",
                "range": "MAX",
            },
        )
    assert response.status_code == 200
    body = response.json()
    port_series = body["benchmark_comparison"]["portfolio"]
    bench_series = body["benchmark_comparison"]["benchmark"]

    # Both series must be weekly: every date must be a Friday (weekday == 4).
    for point in port_series:
        d = dt.date.fromisoformat(point[0])
        assert d.weekday() == 4, f"portfolio comparison point {d} is not a Friday"
    for point in bench_series:
        d = dt.date.fromisoformat(point[0])
        assert d.weekday() == 4, f"benchmark comparison point {d} is not a Friday"

    # Both comparison series must share the same length (symmetric bounding).
    assert len(port_series) == len(bench_series), (
        f"comparison.portfolio has {len(port_series)} points but "
        f"comparison.benchmark has {len(bench_series)}"
    )


async def test_single_chart_grid_when_benchmark_is_shortest(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Single-grid contract: nav, comparison.portfolio, comparison.benchmark share first/last dates.

    When the benchmark starts LATER than the position tickers (younger
    inception), the aligned grid is shorter than the full NAV grid.  After
    fix #2, nav must be sliced to the aligned grid so all three line series
    share the same first and last date — the frontend can plot them on one
    x-axis without a join step.
    """
    # Build a benchmark that starts 60 business days LATER than the positions.
    n_full = N_DAYS
    n_bench_short = n_full - 60  # benchmark is younger

    short_bench_rows = _synthetic_rows(seed=99, n_days=n_bench_short)

    rows_map: dict[str, list[AdjCloseRow]] = {
        "AAPL": _synthetic_rows(seed=1, n_days=n_full),
        "MSFT": _synthetic_rows(seed=2, n_days=n_full),
        "SPY": short_bench_rows,
    }
    _install_stubs(monkeypatch, rows_by_ticker=rows_map)
    transport = ASGITransport(app=_app_with_overrides())
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        response = await ac.post(
            "/portfolio/analysis",
            json={
                "positions": [
                    {"ticker": "AAPL", "weight": 0.6},
                    {"ticker": "MSFT", "weight": 0.4},
                ],
                "mode": "weights",
                "range": "1Y",
                "benchmark": "SPY",
            },
        )
    assert response.status_code == 200
    body = response.json()

    nav_dates = [pt[0] for pt in body["nav"]]
    port_dates = [pt[0] for pt in body["benchmark_comparison"]["portfolio"]]
    bench_dates = [pt[0] for pt in body["benchmark_comparison"]["benchmark"]]

    # All three series must share the same first and last date.
    assert nav_dates[0] == port_dates[0] == bench_dates[0], (
        f"First dates differ: nav={nav_dates[0]}, "
        f"portfolio={port_dates[0]}, benchmark={bench_dates[0]}"
    )
    assert nav_dates[-1] == port_dates[-1] == bench_dates[-1], (
        f"Last dates differ: nav={nav_dates[-1]}, "
        f"portfolio={port_dates[-1]}, benchmark={bench_dates[-1]}"
    )
    assert len(nav_dates) == len(port_dates) == len(bench_dates), (
        f"Series lengths differ: nav={len(nav_dates)}, "
        f"portfolio={len(port_dates)}, benchmark={len(bench_dates)}"
    )


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
    rows = dict(ROWS_BY_TICKER)
    rows["AAPL"] = []
    _install_stubs(monkeypatch, rows_by_ticker=rows)
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
