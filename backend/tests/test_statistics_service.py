"""Unit tests for the statistics service (F5) — pure assemblers + resolver.

No live network, no live DB: the pure ``assemble_*`` functions are fed
synthetic pandas series; ``resolve_asset_returns`` gets its reads stubbed at
the service-module boundary (same approach as the F3.2 route tests).
"""

import datetime as dt
import math
from types import SimpleNamespace
from typing import Any

import numpy as np
import pandas as pd
import pytest
from fastapi import HTTPException
from pydantic import TypeAdapter

from app.analytics import (
    annualized_volatility,
    asset_returns_frame,
    best_worst_day,
    correlation_matrix,
    historical_var,
    nav_by_position,
    portfolio_returns,
    sharpe_ratio,
    simple_returns,
    sortino_ratio,
    weight_series,
)
from app.api import _shared as api_shared
from app.ingestion.service import EnsureReport
from app.schemas.statistics import AssetRef, PortfolioRef, TickerRef
from app.services import statistics as statistics_service
from app.services._series import join_prices
from app.services.statistics import (
    assemble_beta,
    assemble_rolling_correlation,
    assemble_scenario,
    assemble_stock_correlation,
    resolve_asset_returns,
)
from app.services.stock_analysis import InsufficientDataError, PayloadTooLargeError

MAX_POINTS = 7000


def _price_series(seed: int, n_days: int = 300, end: dt.date | None = None) -> pd.Series:
    """Deterministic geometric-random-walk adjusted closes on business days."""
    dates = pd.bdate_range(end=end or dt.date.today(), periods=n_days)
    rng = np.random.default_rng(seed)
    closes = 100.0 * np.cumprod(1 + rng.normal(0.0004, 0.01, n_days))
    return pd.Series(closes, index=dates, name="adj_close")


def _series_map(n_days: int = 300) -> dict[str, pd.Series]:
    return {"AAPL": _price_series(1, n_days), "MSFT": _price_series(2, n_days)}


QUANTITIES = {"AAPL": 10.0, "MSFT": 5.0}


def _scenario(
    series_by_ticker: dict[str, pd.Series] | None = None,
    *,
    cash: float = 0.0,
    max_points: int = MAX_POINTS,
    quantities: dict[str, float] | None = None,
) -> Any:
    return assemble_scenario(
        series_by_ticker if series_by_ticker is not None else _series_map(),
        portfolio_id=7,
        name="Temp",
        quantities=quantities or QUANTITIES,
        cash=cash,
        max_points=max_points,
    )


# ---------------------------------------------------------------------------
# Scenario
# ---------------------------------------------------------------------------


def test_scenario_stacked_series_with_cash() -> None:
    response = _scenario(cash=1000.0)

    nav_tickers = [s.ticker for s in response.nav_cash]
    assert nav_tickers == ["AAPL", "MSFT", "CASH", "TOTAL"]
    weight_tickers = [s.ticker for s in response.weights_percent]
    assert weight_tickers == ["AAPL", "MSFT", "CASH"]
    perf_tickers = [s.ticker for s in response.asset_performance]
    assert perf_tickers == ["AAPL", "MSFT", "TOTAL"]

    by_ticker = {s.ticker: s.points for s in response.nav_cash}
    # CASH is constant; TOTAL = sum of positions + cash at every point.
    assert all(value == pytest.approx(1000.0) for _, value in by_ticker["CASH"])
    for i, (date, total) in enumerate(by_ticker["TOTAL"]):
        parts = sum(by_ticker[t][i][1] for t in ("AAPL", "MSFT", "CASH"))
        assert by_ticker["AAPL"][i][0] == date  # shared grid
        assert total == pytest.approx(parts)

    # Weights (including CASH) sum to 1 on every date.
    weight_points = {s.ticker: s.points for s in response.weights_percent}
    n = len(weight_points["AAPL"])
    for i in range(n):
        total_weight = sum(weight_points[t][i][1] for t in weight_points)
        assert total_weight == pytest.approx(1.0)

    # Asset performance is rebased to exactly 0.0 at the window start.
    for series in response.asset_performance:
        assert series.points[0][1] == 0.0
        assert series.points[0][0] == response.params.start_date

    assert response.params.cash == pytest.approx(1000.0)
    assert response.params.frequency == "daily"
    assert len(response.histogram.counts) == 20


def test_scenario_without_cash_omits_cash_and_matches_engine_weights() -> None:
    series_by_ticker = _series_map()
    response = _scenario(series_by_ticker, cash=0.0)

    assert [s.ticker for s in response.nav_cash] == ["AAPL", "MSFT", "TOTAL"]
    assert [s.ticker for s in response.weights_percent] == ["AAPL", "MSFT"]

    prices = join_prices(series_by_ticker)
    expected = weight_series(prices, QUANTITIES)
    emitted = {s.ticker: s.points for s in response.weights_percent}
    assert emitted["AAPL"][0][1] == pytest.approx(float(expected["AAPL"].iloc[0]))
    assert emitted["MSFT"][-1][1] == pytest.approx(float(expected["MSFT"].iloc[-1]))


def test_scenario_statistics_match_engine() -> None:
    series_by_ticker = _series_map()
    response = _scenario(series_by_ticker, cash=0.0)

    prices = join_prices(series_by_ticker)
    returns = portfolio_returns(prices, QUANTITIES)
    nav = (prices * pd.Series(QUANTITIES)).sum(axis=1)
    stats = response.statistics

    assert stats.annualized_volatility == pytest.approx(annualized_volatility(returns))
    assert stats.var_95 == pytest.approx(historical_var(returns, confidence=0.95))
    assert stats.var_99 == pytest.approx(historical_var(returns, confidence=0.99))
    assert stats.start_nav == pytest.approx(float(nav.iloc[0]))
    assert stats.end_nav == pytest.approx(float(nav.iloc[-1]))
    assert stats.max_nav.value == pytest.approx(float(nav.max()))
    assert stats.min_nav.value == pytest.approx(float(nav.min()))
    assert stats.max_nav.date == nav.idxmax().date()
    assert stats.min_nav.date == nav.idxmin().date()
    best_worst = best_worst_day(returns)
    assert stats.max_return.value == pytest.approx(best_worst.best_return)
    assert stats.max_return.date == best_worst.best_date
    assert stats.min_return.value == pytest.approx(best_worst.worst_return)
    assert stats.min_return.date == best_worst.worst_date
    assert stats.start_date == response.params.start_date
    assert stats.end_date == response.params.end_date

    # TOTAL nav points reproduce the engine NAV at both ends.
    total = next(s for s in response.nav_cash if s.ticker == "TOTAL").points
    assert total[0][1] == pytest.approx(float(nav.iloc[0]))
    assert total[-1][1] == pytest.approx(float(nav.iloc[-1]))


def test_scenario_short_window_names_shortest_ticker() -> None:
    series_by_ticker = {"AAPL": _price_series(1), "MSFT": _price_series(2, n_days=5)}
    with pytest.raises(InsufficientDataError, match="MSFT"):
        _scenario(series_by_ticker)


def test_scenario_empty_join_reports_no_rows() -> None:
    empty = pd.Series([], index=pd.DatetimeIndex([]), dtype=float)
    series_by_ticker = {"AAPL": _price_series(1), "MSFT": empty}
    with pytest.raises(InsufficientDataError, match="MSFT"):
        _scenario(series_by_ticker)


def test_scenario_window_exceeding_max_points_is_rejected() -> None:
    with pytest.raises(PayloadTooLargeError, match="Narrow"):
        _scenario(max_points=100)


def test_scenario_weekly_bounding_applies_to_all_series() -> None:
    response = _scenario(_series_map(n_days=1400))
    assert response.params.frequency == "weekly"
    all_series = (
        response.nav_cash + response.weights_percent + response.asset_performance
    )
    lengths = {len(s.points) for s in all_series}
    assert len(lengths) == 1  # every series shares the same weekly grid
    for series in all_series:
        for date, _ in series.points:
            assert date.weekday() == 4, f"{series.ticker} point {date} is not a Friday"


# ---------------------------------------------------------------------------
# Pseudo-asset resolution
# ---------------------------------------------------------------------------


def _install_resolver_stubs(
    monkeypatch: pytest.MonkeyPatch,
    rows_map: dict[str, pd.Series],
    portfolio: Any | None,
) -> None:
    async def fake_ensure(*args: Any, **kwargs: Any) -> EnsureReport:
        return EnsureReport()

    async def fake_rows(
        session: Any, ticker: str, start: dt.date, end: dt.date
    ) -> list[tuple[dt.date, float]]:
        series = rows_map.get(ticker)
        if series is None:
            return []
        sliced = series[(series.index.date >= start) & (series.index.date <= end)]
        return [(ts.date(), float(v)) for ts, v in sliced.items()]

    async def fake_get_portfolio(
        session: Any, portfolio_id: int, owner_sub: str
    ) -> Any | None:
        return portfolio if portfolio is not None and portfolio.id == portfolio_id else None

    async def fake_fund_tickers(session: Any, tickers: Any) -> set[str]:
        return set()

    monkeypatch.setattr(api_shared, "ensure_eod_data", fake_ensure)
    monkeypatch.setattr(statistics_service, "_select_adj_close_rows", fake_rows)
    monkeypatch.setattr(statistics_service.portfolio_crud, "get_portfolio", fake_get_portfolio)
    monkeypatch.setattr(
        statistics_service.portfolio_crud, "select_fund_tickers", fake_fund_tickers
    )


def _fake_portfolio(
    portfolio_id: int = 7, positions: list[tuple[str, float]] | None = None
) -> Any:
    if positions is None:
        positions = [("AAPL", 10.0), ("MSFT", 5.0)]
    return SimpleNamespace(
        id=portfolio_id,
        name="Temp F5",
        cash=1000.0,
        positions=[SimpleNamespace(ticker=t, quantity=q) for t, q in positions],
    )


async def test_resolve_ticker_ref(monkeypatch: pytest.MonkeyPatch) -> None:
    rows_map = {"SPY": _price_series(3)}
    _install_resolver_stubs(monkeypatch, rows_map, portfolio=None)
    start = rows_map["SPY"].index[0].date()
    end = rows_map["SPY"].index[-1].date()

    label, returns = await resolve_asset_returns(
        None, object(), TickerRef(kind="ticker", ticker="SPY"), start, end, "test-sub"
    )
    assert label == "SPY"
    # check_index_type=False: the DB round-trip (Timestamp -> date -> Timestamp)
    # changes only the index unit (s vs us), not the dates.
    pd.testing.assert_series_equal(
        returns,
        simple_returns(rows_map["SPY"]),
        check_index_type=False,
        check_names=False,
        check_freq=False,
    )


async def test_resolve_portfolio_ref_equals_portfolio_returns(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    rows_map = _series_map()
    portfolio = _fake_portfolio()
    _install_resolver_stubs(monkeypatch, rows_map, portfolio)
    start = rows_map["AAPL"].index[0].date()
    end = rows_map["AAPL"].index[-1].date()

    label, returns = await resolve_asset_returns(
        None, object(), PortfolioRef(kind="portfolio", id=7), start, end, "test-sub"
    )
    assert label == "Temp F5"
    prices = join_prices(rows_map)
    expected = portfolio_returns(prices, QUANTITIES)
    pd.testing.assert_series_equal(
        returns, expected, check_names=False, check_index_type=False, check_freq=False
    )


async def test_resolve_unknown_portfolio_raises_404(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_resolver_stubs(monkeypatch, _series_map(), portfolio=None)
    with pytest.raises(HTTPException) as excinfo:
        await resolve_asset_returns(
            None,
            object(),
            PortfolioRef(kind="portfolio", id=99),
            dt.date(2025, 1, 1),
            dt.date(2026, 1, 1),
            "test-sub",
        )
    assert excinfo.value.status_code == 404


async def test_resolve_empty_portfolio_raises_insufficient(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_resolver_stubs(monkeypatch, {}, _fake_portfolio(positions=[]))
    with pytest.raises(InsufficientDataError, match="no positions"):
        await resolve_asset_returns(
            None,
            object(),
            PortfolioRef(kind="portfolio", id=7),
            dt.date(2025, 1, 1),
            dt.date(2026, 1, 1),
            "test-sub",
        )


async def test_resolve_ticker_with_short_history_raises_insufficient(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_resolver_stubs(monkeypatch, {"SPY": _price_series(3, n_days=4)}, None)
    with pytest.raises(InsufficientDataError, match="SPY"):
        await resolve_asset_returns(
            None,
            object(),
            TickerRef(kind="ticker", ticker="SPY"),
            dt.date(2000, 1, 1),
            dt.date.today(),
            "test-sub",
        )


def test_asset_ref_discriminated_union_parses_both_shapes() -> None:
    adapter: TypeAdapter[Any] = TypeAdapter(AssetRef)
    ticker_ref = adapter.validate_python({"kind": "ticker", "ticker": " spy "})
    assert isinstance(ticker_ref, TickerRef)
    assert ticker_ref.ticker == "SPY"
    portfolio_ref = adapter.validate_python({"kind": "portfolio", "id": 3})
    assert isinstance(portfolio_ref, PortfolioRef)
    assert portfolio_ref.id == 3
    with pytest.raises(ValueError):
        adapter.validate_python({"kind": "index", "ticker": "SPX"})


# ---------------------------------------------------------------------------
# Beta
# ---------------------------------------------------------------------------


def test_beta_y_equals_2x_plus_offset() -> None:
    rng = np.random.default_rng(11)
    dates = pd.bdate_range(end=dt.date.today(), periods=120)
    x = pd.Series(rng.normal(0.0, 0.01, len(dates)), index=dates)
    y = 2.0 * x + 0.001

    response = assemble_beta("X", x, "Y", y, max_points=MAX_POINTS)
    reg = response.regression
    assert reg.beta == pytest.approx(2.0)
    assert reg.r == pytest.approx(1.0)
    # alpha = mean_y - beta * mean_x = (2*mean_x + 0.001) - 2*mean_x = 0.001
    assert reg.alpha == pytest.approx(0.001)
    assert reg.n_points == len(dates)
    assert response.labels.x == "X"
    assert response.labels.y == "Y"

    assert len(response.scatter) == len(dates)
    # Regression line endpoints: y = alpha + beta * x at min(x) and max(x).
    x_values = [p[0] for p in response.scatter]
    (x0, y0), (x1, y1) = response.regression_line
    assert x0 == pytest.approx(min(x_values))
    assert x1 == pytest.approx(max(x_values))
    assert y0 == pytest.approx(reg.alpha + reg.beta * x0)
    assert y1 == pytest.approx(reg.alpha + reg.beta * x1)


def test_beta_scatter_is_bounded() -> None:
    dates = pd.bdate_range(end=dt.date.today(), periods=50)
    rng = np.random.default_rng(12)
    x = pd.Series(rng.normal(0.0, 0.01, len(dates)), index=dates)
    with pytest.raises(PayloadTooLargeError, match="Narrow"):
        assemble_beta("X", x, "Y", 2 * x, max_points=10)


def test_beta_too_few_points_raises_insufficient() -> None:
    dates = pd.bdate_range(end=dt.date.today(), periods=5)
    x = pd.Series([0.01, -0.02, 0.005, 0.0, 0.01], index=dates)
    with pytest.raises(InsufficientDataError):
        assemble_beta("X", x, "Y", 2 * x, max_points=MAX_POINTS)


# ---------------------------------------------------------------------------
# Rolling correlation
# ---------------------------------------------------------------------------


def test_rolling_correlation_identical_assets_is_all_ones() -> None:
    prices = _price_series(5, n_days=300)
    returns = simple_returns(prices)
    start = returns.index[120].date()  # plenty of pre-start pad for window=63

    response = assemble_rolling_correlation(
        "A", returns, "B", returns.copy(), window=63, start=start, max_points=MAX_POINTS
    )
    assert response.window == 63
    assert response.current == pytest.approx(1.0)
    assert all(value == pytest.approx(1.0) for _, value in response.series)
    # Warm from day one: the first emitted point is right after `start`
    # (strictly-after slicing, F2.2 convention), not window days later.
    first_date = response.series[0][0]
    assert start < first_date <= returns.index[123].date()


def test_rolling_correlation_insufficient_history_raises() -> None:
    prices = _price_series(6, n_days=30)
    returns = simple_returns(prices)
    with pytest.raises(InsufficientDataError):
        assemble_rolling_correlation(
            "A",
            returns,
            "B",
            returns.copy(),
            window=63,
            start=returns.index[0].date(),
            max_points=MAX_POINTS,
        )


# ---------------------------------------------------------------------------
# Stock correlation
# ---------------------------------------------------------------------------


def test_stock_correlation_matrix_symmetric_unit_diagonal() -> None:
    series_by_ticker = {
        "AAPL": _price_series(1),
        "MSFT": _price_series(2),
        "SPY": _price_series(3),
    }
    response = assemble_stock_correlation(series_by_ticker, window=63)
    assert response.tickers == ["AAPL", "MSFT", "SPY"]
    assert response.window == 63
    matrix = response.matrix
    assert len(matrix) == 3 and all(len(row) == 3 for row in matrix)
    for i in range(3):
        assert matrix[i][i] == 1.0
        for j in range(3):
            assert matrix[i][j] == pytest.approx(matrix[j][i])
            assert -1.0 <= matrix[i][j] <= 1.0
    assert response.as_of == series_by_ticker["AAPL"].index[-1].date()


def test_stock_correlation_uses_exactly_the_trailing_window() -> None:
    """The matrix must come from EXACTLY the last `window` returns."""
    window = 20
    series_by_ticker = {"AAPL": _price_series(8), "MSFT": _price_series(9)}
    response = assemble_stock_correlation(series_by_ticker, window=window)

    prices = join_prices(series_by_ticker)
    tail = prices.iloc[-(window + 1) :]
    tail_returns = asset_returns_frame(tail)
    assert len(tail_returns) == window  # exactly `window` returns feed the matrix
    expected = correlation_matrix(tail_returns)
    assert response.matrix[0][1] == pytest.approx(float(expected.iloc[0, 1]))

    # Sanity: the full-history correlation differs — the slice matters.
    full = correlation_matrix(asset_returns_frame(prices))
    assert response.matrix[0][1] != pytest.approx(float(full.iloc[0, 1]))


def test_stock_correlation_insufficient_history_names_ticker() -> None:
    series_by_ticker = {"AAPL": _price_series(1), "MSFT": _price_series(2, n_days=30)}
    with pytest.raises(InsufficientDataError, match="MSFT"):
        assemble_stock_correlation(series_by_ticker, window=63)


# ---------------------------------------------------------------------------
# Scenario: cash + weekly bounding combined
# ---------------------------------------------------------------------------


def test_scenario_cash_and_weekly_bounding() -> None:
    """cash>0 AND ≥1400 trading days: CASH series present, all points Fridays,
    weekly weight rows still sum to 1 (1e-9 tolerance)."""
    n_days = 1400
    series_by_ticker = _series_map(n_days=n_days)
    response = _scenario(series_by_ticker, cash=5000.0)

    # Weekly bounding must have kicked in.
    assert response.params.frequency == "weekly"
    assert response.params.cash == pytest.approx(5000.0)

    # CASH series is present in nav_cash and weights_percent.
    nav_tickers = [s.ticker for s in response.nav_cash]
    assert "CASH" in nav_tickers
    assert "TOTAL" in nav_tickers

    weight_tickers = [s.ticker for s in response.weights_percent]
    assert "CASH" in weight_tickers

    # Every emitted date across ALL series must be a Friday (weekday == 4).
    all_series = response.nav_cash + response.weights_percent + response.asset_performance
    for series in all_series:
        for date, _ in series.points:
            assert date.weekday() == 4, (
                f"{series.ticker} weekly point {date} is not a Friday"
            )

    # Weights sum to 1 on every row (cash column included → same invariant as daily).
    weight_points = {s.ticker: s.points for s in response.weights_percent}
    n_points = len(weight_points["AAPL"])
    for i in range(n_points):
        row_sum = sum(weight_points[t][i][1] for t in weight_points)
        assert row_sum == pytest.approx(1.0, abs=1e-9)


# --- Sharpe/Sortino in ScenarioStatistics (T1A-7) ----------------------------


def test_scenario_statistics_carry_sharpe_sortino() -> None:
    series = _series_map(300)
    resp = assemble_scenario(
        series,
        portfolio_id=1,
        name="Test",
        quantities=QUANTITIES,
        cash=0.0,
        max_points=MAX_POINTS,
    )
    stats = resp.statistics
    assert math.isfinite(stats.sharpe_ratio)
    assert math.isfinite(stats.sortino_ratio)


def test_scenario_statistics_sharpe_matches_engine_on_total_returns() -> None:
    series = _series_map(300)
    resp = assemble_scenario(
        series,
        portfolio_id=1,
        name="Test",
        quantities=QUANTITIES,
        cash=0.0,
        max_points=MAX_POINTS,
    )
    # Rebuild the cash-inclusive total daily returns the assembler computes:
    # values = nav_by_position(prices, quantities); total = values.sum(axis=1) + cash.
    prices = join_prices(series)
    total = nav_by_position(prices, QUANTITIES).sum(axis=1) + 0.0
    total_returns = simple_returns(total)
    assert resp.statistics.sharpe_ratio == pytest.approx(
        sharpe_ratio(total_returns), rel=1e-9
    )
    assert resp.statistics.sortino_ratio == pytest.approx(
        sortino_ratio(total_returns), rel=1e-9
    )
