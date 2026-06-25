"""Statistics-group service (F5): scenario replay, pseudo-asset comparisons,
holdings correlation.

Structure (the F2/F3 pattern):
- pure ``assemble_*`` functions: pandas → response schema, no I/O — unit-tested
  directly on synthetic frames;
- async ``run_*`` orchestrators: read adjusted closes from the local DB, then
  call the pure assembler.
  Routes stay thin: validate → run → map ``StockAnalysisError`` to 422.

Replay semantics (documented on the schemas too): a persisted portfolio is
ALWAYS replayed at its CURRENT quantities held fixed over the window —
buy-and-hold historical replay ("what would this portfolio have done?"), not a
reconstruction of past trades. See ``app.analytics.portfolio``.

Error contract (fail loud, never silently empty):
- unknown portfolio                          -> HTTPException 404;
- unknown ticker / missing local price rows  -> ``InsufficientDataError`` (422);
- empty portfolio / insufficient history /
  engine-undefined statistics               -> ``InsufficientDataError`` (422);
- oversized window                           -> ``PayloadTooLargeError`` (422).

Scale contract (project-wide): all fractional quantities are decimal
fractions (0.05 = 5%), never 0-100. NAV values are currency units.
"""

import datetime as dt
from collections.abc import Callable, Mapping

import pandas as pd
from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.analytics import (
    MIN_IN_RANGE_RETURNS,
    align_returns,
    annualized_volatility,
    asset_returns_frame,
    best_worst_day,
    beta,
    correlation,
    correlation_matrix,
    historical_var,
    nav_by_position,
    portfolio_returns,
    return_histogram,
    rolling_correlation,
    sharpe_ratio,
    simple_returns,
    sortino_ratio,
    weight_series,
)
from app.analytics._validation import to_date as _to_date
from app.models.portfolio import Portfolio
from app.schemas.analysis import DatedValue, HistogramOut
from app.schemas.statistics import (
    AssetRef,
    AxisLabels,
    BetaRequest,
    BetaResponse,
    CorrelationRequest,
    CorrelationResponse,
    DatedNav,
    RegressionOut,
    ScenarioParams,
    ScenarioRequest,
    ScenarioResponse,
    ScenarioStatistics,
    StackedSeries,
    StockCorrelationRequest,
    StockCorrelationResponse,
    TickerRef,
)
from app.services import portfolio_crud
from app.services._series import (
    join_prices as _join_prices,
)
from app.services._series import (
    rebased_cumulative as _rebased_cumulative,
)
from app.services._series import (
    rebased_cumulative_weekly as _rebased_cumulative_weekly,
)
from app.services._series import (
    resample_weekly as _resample_weekly,
)
from app.services._series import (
    select_adj_close_rows as _select_adj_close_rows,
)
from app.services._series import (
    series_points as _series_points,
)
from app.services._series import (
    shortest_history_ticker as _shortest_history_ticker,
)
from app.core.result_cache import cached_result, portfolio_version_hash
from app.services.stock_analysis import (
    InsufficientDataError,
    PayloadTooLargeError,
    build_adj_close_series,
    lookback_pad_days,
)
from pydantic import BaseModel

_HISTOGRAM_BINS = 20

# Weekly (W-FRI) bounding threshold for the scenario line series: above 1260
# daily points (~5 trading years — the same budget as the 5Y range preset) ALL
# series switch to last-of-week consistently. Statistics stay daily.
WEEKLY_BOUND_POINTS = 1260

CASH_LABEL = "CASH"
TOTAL_LABEL = "TOTAL"


def _engine[T](func: Callable[..., T], *args: object, **kwargs: object) -> T:
    """Run an engine function, mapping its fail-loud ValueError to a 422 error.

    The engine refuses undefined statistics (too few points, zero variance)
    with ValueError; at the service boundary that is an unprocessable request,
    so the actionable message is re-raised as ``InsufficientDataError``.
    """
    try:
        return func(*args, **kwargs)
    except ValueError as exc:
        raise InsufficientDataError(str(exc)) from exc


def _require_common_rows(
    series_by_ticker: Mapping[str, pd.Series],
    prices: pd.DataFrame,
    min_rows: int,
    requirement: str,
) -> None:
    """422 naming the shortest-history ticker when the inner join is too short
    (the F3.2 message pattern)."""
    if len(prices) >= min_rows:
        return
    offender = _shortest_history_ticker(series_by_ticker)
    offender_series = series_by_ticker[offender]
    inception = (
        f" (history starts {_to_date(offender_series.index[0]).isoformat()})"
        if len(offender_series)
        else " (no price rows in the window)"
    )
    raise InsufficientDataError(
        f"Only {len(prices)} trading days are shared by ALL tickers in the window — "
        f"at least {min_rows} are required {requirement}. {offender} has the "
        f"shortest history{inception}. Use a wider window or adjust the holdings."
    )


async def _load_series_map(
    session: AsyncSession, tickers: list[str], start: dt.date, end: dt.date
) -> dict[str, pd.Series]:
    """Read per-ticker adjusted-close series over [start, end] (insertion order)."""
    return {
        ticker: build_adj_close_series(
            await _select_adj_close_rows(session, ticker, start, end)
        )
        for ticker in tickers
    }


async def _load_portfolio_or_404(
    session: AsyncSession, portfolio_id: int
) -> Portfolio:
    portfolio = await portfolio_crud.get_portfolio(session, portfolio_id)
    if portfolio is None:
        raise HTTPException(
            status_code=404, detail=f"Portfolio {portfolio_id} not found."
        )
    return portfolio


def _require_positions(portfolio: Portfolio) -> dict[str, float]:
    """Quantities map of a portfolio; 422 when it holds no positions."""
    if not portfolio.positions:
        raise InsufficientDataError(
            f"Portfolio {portfolio.name!r} has no positions — nothing to analyze. "
            "Add at least one position first."
        )
    return {p.ticker: float(p.quantity) for p in portfolio.positions}


async def _load_portfolio_prices(
    session: AsyncSession,
    portfolio_id: int,
    start: dt.date,
    end: dt.date,
) -> tuple[Portfolio, dict[str, float], dict[str, pd.Series]]:
    """Load, validate and read prices for a portfolio in one call.

    Sequence: _load_portfolio_or_404 → _require_positions → build tickers list
    → _load_series_map.

    Returns:
        portfolio: the ORM object (for name, cash, id, etc.)
        quantities: ``{ticker: float(quantity)}`` map of current holdings.
        series_by_ticker: per-ticker adjusted-close series over [start, end].

    Raises:
        HTTPException 404: unknown portfolio_id.
        InsufficientDataError: portfolio has no positions, or holds fund
            positions (NAV-priced — not supported by the EOD analyses yet).
    """
    portfolio = await _load_portfolio_or_404(session, portfolio_id)
    quantities = _require_positions(portfolio)
    tickers = list(quantities)
    # Fund positions (F8.5 saved proposals) are NAV-priced and have no EOD
    # rows — the replay/beta/correlation engines are not fund-aware yet.
    # Cheap guard: clear 422 instead of a missing-local-price error downstream.
    fund_tickers = await portfolio_crud.select_fund_tickers(session, tickers)
    if fund_tickers:
        raise InsufficientDataError(
            "fund positions not yet supported in this analysis: "
            f"{', '.join(sorted(fund_tickers))}"
        )
    series_by_ticker = await _load_series_map(session, tickers, start, end)
    missing = [ticker for ticker, series in series_by_ticker.items() if series.empty]
    if missing:
        raise InsufficientDataError(
            "No local price data available for: "
            f"{', '.join(sorted(missing))}. Run the EOD backfill before analysis."
        )
    return portfolio, quantities, series_by_ticker


# ---------------------------------------------------------------------------
# Pseudo-asset resolution (the ONE resolver used by beta and correlation)
# ---------------------------------------------------------------------------


async def resolve_asset_returns(
    session: AsyncSession,
    ref: AssetRef,
    start: dt.date,
    end: dt.date,
) -> tuple[str, pd.Series]:
    """Resolve a pseudo-asset reference into ``(label, daily return series)``.

    - ``kind='ticker'``: local adjusted closes over [start, end]; label = the ticker.
    - ``kind='portfolio'``: load the persisted portfolio (404 when unknown),
      replay its CURRENT quantities (inner-join of its holdings' adjusted
      closes, engine ``portfolio_returns``); label = the portfolio name.
      Uninvested cash is NOT included — it is constant and would only dilute
      beta/correlation against the invested positions.

    Raises:
        HTTPException: 404 for an unknown portfolio.
        InsufficientDataError: empty portfolio, or too few common trading days
            in the window (the shortest-history ticker is named).
    """
    if isinstance(ref, TickerRef):
        series = (await _load_series_map(session, [ref.ticker], start, end))[ref.ticker]
        if series.empty:
            raise HTTPException(
                status_code=404,
                detail=(
                    f"No local price data available for {ref.ticker}. "
                    "Run the EOD backfill before analysis."
                ),
            )
        if len(series) < MIN_IN_RANGE_RETURNS + 1:
            raise InsufficientDataError(
                f"Only {len(series)} price rows for {ref.ticker} between {start} and "
                f"{end} — at least {MIN_IN_RANGE_RETURNS + 1} are required. "
                "Use a wider window."
            )
        return ref.ticker, simple_returns(series)

    portfolio, quantities, series_by_ticker = await _load_portfolio_prices(
        session, ref.id, start, end
    )
    prices = _join_prices(series_by_ticker)
    _require_common_rows(
        series_by_ticker,
        prices,
        MIN_IN_RANGE_RETURNS + 1,
        "to replay the portfolio",
    )
    return portfolio.name, portfolio_returns(prices, quantities)


# ---------------------------------------------------------------------------
# POST /statistics/scenario
# ---------------------------------------------------------------------------


def assemble_scenario(
    series_by_ticker: Mapping[str, pd.Series],
    *,
    portfolio_id: int,
    name: str,
    quantities: Mapping[str, float],
    cash: float,
    max_points: int,
) -> ScenarioResponse:
    """Assemble the scenario payload from per-ticker adjusted-close series.

    Pure pandas — no I/O. Replay semantics: ``quantities`` (the portfolio's
    CURRENT holdings) are held fixed over the whole inner-joined window;
    ``cash`` is a constant (no interest model — it earns exactly zero return,
    dampening the cash-inclusive total's volatility, which is the honest
    answer for an uninvested balance).

    Bounding: more than ``max_points`` joined trading days is rejected (422);
    above ``WEEKLY_BOUND_POINTS`` daily points ALL line series are resampled
    to W-FRI last-of-week consistently (``params.frequency = "weekly"``).
    Statistics and the histogram are ALWAYS computed on daily data.

    Raises:
        InsufficientDataError: too few common trading days (shortest-history
            ticker named).
        PayloadTooLargeError: window exceeds ``max_points`` trading days.
    """
    prices = _join_prices(series_by_ticker)
    _require_common_rows(
        series_by_ticker,
        prices,
        MIN_IN_RANGE_RETURNS + 1,
        "for the scenario statistics",
    )
    if len(prices) > max_points:
        raise PayloadTooLargeError(
            f"The window spans {len(prices)} trading days, exceeding the maximum of "
            f"{max_points}. Narrow the date range."
        )
    weekly = len(prices) > WEEKLY_BOUND_POINTS

    def _points(series: pd.Series) -> list[tuple[dt.date, float]]:
        return _series_points(_resample_weekly(series) if weekly else series)

    def _rebased(returns: pd.Series) -> list[tuple[dt.date, float]]:
        """Cumulative-return points rebased to 0.0 at the FIRST PRICE date.

        ``returns`` starts at the second price date; prepending a synthetic
        zero-return at the first price date makes the rebasing helpers emit
        (first_date, 0.0) — the same trick as the F3.2 benchmark comparison.
        """
        zero = pd.Series([0.0], index=prices.index[:1])
        extended = pd.concat([zero, returns])
        return (
            _rebased_cumulative_weekly(extended)
            if weekly
            else _rebased_cumulative(extended)
        )

    # REPLAY view (one engine): per-position values, NAV, weights.
    values = nav_by_position(prices, quantities)
    nav_positions = values.sum(axis=1)
    total = nav_positions + cash
    tickers = [str(c) for c in prices.columns]

    nav_cash = [
        StackedSeries(ticker=ticker, points=_points(values[ticker]))
        for ticker in tickers
    ]
    if cash > 0:
        cash_series = pd.Series(float(cash), index=prices.index)
        nav_cash.append(StackedSeries(ticker=CASH_LABEL, points=_points(cash_series)))
    nav_cash.append(StackedSeries(ticker=TOTAL_LABEL, points=_points(total)))

    # Weights: engine weight_series when there is no cash; with cash > 0 the
    # same math over the value frame extended by the constant cash column
    # (each row still sums to 1 across the emitted series).
    if cash > 0:
        extended_values = values.copy()
        extended_values[CASH_LABEL] = float(cash)
        weights = extended_values.div(extended_values.sum(axis=1), axis=0)
    else:
        weights = weight_series(prices, quantities)
    weights_percent = [
        StackedSeries(ticker=str(column), points=_points(weights[column]))
        for column in weights.columns
    ]

    # Asset performance: per-position cumulative return rebased to 0.0 at the
    # window start, plus the cash-inclusive TOTAL on the same grid.
    asset_performance = [
        StackedSeries(ticker=ticker, points=_rebased(simple_returns(prices[ticker])))
        for ticker in tickers
    ]
    total_returns = simple_returns(total)
    asset_performance.append(
        StackedSeries(ticker=TOTAL_LABEL, points=_rebased(total_returns))
    )

    # Statistics rail + histogram: DAILY returns of the cash-inclusive total
    # (>= MIN_IN_RANGE_RETURNS returns guaranteed by the join guard above).
    # _engine wraps the block so any engine-layer ValueError (e.g. zero-variance
    # total caused by an all-cash window) surfaces as a 422 InsufficientDataError
    # rather than an unhandled 500 (422-parity with the beta/correlation paths).
    def _build_stats() -> tuple[HistogramOut, ScenarioStatistics]:
        histogram = return_histogram(total_returns, bins=_HISTOGRAM_BINS)
        best_worst = best_worst_day(total_returns)
        max_label = total.idxmax()
        min_label = total.idxmin()
        stats = ScenarioStatistics(
            start_date=_to_date(prices.index[0]),
            end_date=_to_date(prices.index[-1]),
            start_nav=float(total.iloc[0]),
            end_nav=float(total.iloc[-1]),
            max_nav=DatedNav(date=_to_date(max_label), value=float(total.loc[max_label])),
            min_nav=DatedNav(date=_to_date(min_label), value=float(total.loc[min_label])),
            max_return=DatedValue(date=best_worst.best_date, value=best_worst.best_return),
            min_return=DatedValue(date=best_worst.worst_date, value=best_worst.worst_return),
            annualized_volatility=annualized_volatility(total_returns),
            var_95=historical_var(total_returns, confidence=0.95),
            var_99=historical_var(total_returns, confidence=0.99),
            sharpe_ratio=sharpe_ratio(total_returns),
            sortino_ratio=sortino_ratio(total_returns),
        )
        return HistogramOut(
            bin_edges=histogram.bin_edges,
            counts=histogram.counts,
            counts_normalized=histogram.counts_normalized,
        ), stats

    histogram_out, statistics = _engine(_build_stats)

    return ScenarioResponse(
        params=ScenarioParams(
            portfolio_id=portfolio_id,
            name=name,
            start_date=_to_date(prices.index[0]),
            end_date=_to_date(prices.index[-1]),
            cash=float(cash),
            frequency="weekly" if weekly else "daily",
        ),
        nav_cash=nav_cash,
        weights_percent=weights_percent,
        asset_performance=asset_performance,
        histogram=histogram_out,
        statistics=statistics,
    )


async def run_scenario(
    session: AsyncSession,
    payload: ScenarioRequest,
    *,
    max_points: int,
) -> ScenarioResponse:
    """Orchestrate the scenario: load portfolio, read local prices, assemble."""
    portfolio, quantities, series_by_ticker = await _load_portfolio_prices(
        session, payload.portfolio_id, payload.start_date, payload.end_date
    )
    return assemble_scenario(
        series_by_ticker,
        portfolio_id=portfolio.id,
        name=portfolio.name,
        quantities=quantities,
        cash=float(portfolio.cash),
        max_points=max_points,
    )


class _VersionedScenario(BaseModel):
    """Payload de cache: request + hash de versão do portfólio (invalida ao editar)."""

    request: ScenarioRequest
    portfolio_version: str


@cached_result("stat_scenario")
async def _run_scenario_cached(
    session: AsyncSession, payload: _VersionedScenario, *, max_points: int
) -> ScenarioResponse:
    return await run_scenario(session, payload.request, max_points=max_points)


# ---------------------------------------------------------------------------
# POST /statistics/beta
# ---------------------------------------------------------------------------


def assemble_beta(
    label_x: str,
    returns_x: pd.Series,
    label_y: str,
    returns_y: pd.Series,
    *,
    max_points: int,
) -> BetaResponse:
    """Scatter + regression of y's daily returns on x's (pure pandas).

    ``beta`` (the slope) and ``r`` come from the engine; ``alpha`` is the OLS
    intercept derived from the engine beta — ``mean_y - beta * mean_x`` over
    the aligned returns, in DAILY decimal-return units (the only arithmetic
    not delegated: two means and one multiply). The regression line is emitted
    as two endpoints, y = alpha + beta * x at min(x) and max(x).

    Raises:
        InsufficientDataError: too few aligned points or zero variance.
        PayloadTooLargeError: more than ``max_points`` aligned pairs.
    """
    aligned_x, aligned_y = _engine(align_returns, returns_x, returns_y)
    if len(aligned_x) > max_points:
        raise PayloadTooLargeError(
            f"The window yields {len(aligned_x)} aligned return pairs, exceeding the "
            f"maximum of {max_points}. Narrow the date range."
        )
    # Engine beta(asset, benchmark) = cov / var(benchmark): regressing y on x
    # means x is the benchmark.
    slope = _engine(beta, aligned_y, aligned_x)
    r = _engine(correlation, aligned_x, aligned_y)
    mean_x = float(aligned_x.mean())
    mean_y = float(aligned_y.mean())
    alpha = mean_y - slope * mean_x
    x_values = aligned_x.to_numpy(dtype=float)
    y_values = aligned_y.to_numpy(dtype=float)
    x_min = float(x_values.min())
    x_max = float(x_values.max())
    return BetaResponse(
        labels=AxisLabels(x=label_x, y=label_y),
        scatter=[
            (float(x), float(y)) for x, y in zip(x_values, y_values, strict=True)
        ],
        regression=RegressionOut(
            beta=slope, alpha=alpha, r=r, n_points=len(aligned_x)
        ),
        regression_line=[
            (x_min, alpha + slope * x_min),
            (x_max, alpha + slope * x_max),
        ],
    )


@cached_result("stat_beta")
async def run_beta(
    session: AsyncSession,
    payload: BetaRequest,
    *,
    max_points: int,
) -> BetaResponse:
    """Orchestrate the beta scatter: resolve both pseudo-assets, assemble."""
    label_x, returns_x = await resolve_asset_returns(
        session, payload.asset_x, payload.start_date, payload.end_date
    )
    label_y, returns_y = await resolve_asset_returns(
        session, payload.asset_y, payload.start_date, payload.end_date
    )
    return assemble_beta(
        label_x, returns_x, label_y, returns_y, max_points=max_points
    )


# ---------------------------------------------------------------------------
# POST /statistics/correlation
# ---------------------------------------------------------------------------


def assemble_rolling_correlation(
    label_x: str,
    returns_x: pd.Series,
    label_y: str,
    returns_y: pd.Series,
    *,
    window: int,
    start: dt.date,
    max_points: int,
) -> CorrelationResponse:
    """Rolling correlation sliced to the requested window (pure pandas).

    The inputs cover ``[start - lookback_pad, end]`` (the F2.2 pattern): the
    pad warms up the rolling window so the emitted series covers the requested
    window from (approximately) its first trading day. The series is sliced to
    dates strictly after ``start`` (same in-range convention as F2.2) and NaN
    rows (warm-up / undefined windows) are dropped.

    Raises:
        InsufficientDataError: fewer aligned points than ``window``, or no
            defined in-range point.
        PayloadTooLargeError: more than ``max_points`` emitted points.
    """
    series = _engine(rolling_correlation, returns_x, returns_y, window)
    in_range = series[series.index > pd.Timestamp(start)].dropna()
    if in_range.empty:
        raise InsufficientDataError(
            f"No defined rolling-correlation point after {start} for a window of "
            f"{window} trading days. Use a wider window of dates or a smaller "
            "rolling window."
        )
    if len(in_range) > max_points:
        raise PayloadTooLargeError(
            f"The window yields {len(in_range)} rolling-correlation points, exceeding "
            f"the maximum of {max_points}. Narrow the date range."
        )
    points = _series_points(in_range)
    return CorrelationResponse(
        labels=AxisLabels(x=label_x, y=label_y),
        window=window,
        series=points,
        current=points[-1][1],
    )


@cached_result("stat_rolling_correlation")
async def run_rolling_correlation(
    session: AsyncSession,
    payload: CorrelationRequest,
    *,
    max_points: int,
) -> CorrelationResponse:
    """Orchestrate rolling correlation: resolve with a lookback pad, assemble.

    Both pseudo-assets are resolved over ``[start - lookback_pad(window), end]``
    so the rolling window is warm at the requested start (F2.2 pattern).
    """
    pad_start = payload.start_date - dt.timedelta(
        days=lookback_pad_days(payload.window)
    )
    label_x, returns_x = await resolve_asset_returns(
        session, payload.asset_x, pad_start, payload.end_date
    )
    label_y, returns_y = await resolve_asset_returns(
        session, payload.asset_y, pad_start, payload.end_date
    )
    return assemble_rolling_correlation(
        label_x,
        returns_x,
        label_y,
        returns_y,
        window=payload.window,
        start=payload.start_date,
        max_points=max_points,
    )


# ---------------------------------------------------------------------------
# POST /statistics/stock-correlation
# ---------------------------------------------------------------------------


def assemble_stock_correlation(
    series_by_ticker: Mapping[str, pd.Series],
    *,
    window: int,
) -> StockCorrelationResponse:
    """Pairwise correlation matrix over the TRAILING window (pure pandas).

    The inner-joined frame is cut to its last ``window + 1`` closes, yielding
    EXACTLY ``window`` trading-day returns per holding; the engine
    ``correlation_matrix`` does the rest.

    Raises:
        InsufficientDataError: fewer than ``window + 1`` common closes (the
            shortest-history ticker is named) or zero-variance holdings.
    """
    prices = _join_prices(series_by_ticker)
    _require_common_rows(
        series_by_ticker,
        prices,
        window + 1,
        f"for a {window}-day correlation window (window + 1 closes)",
    )
    tail = prices.iloc[-(window + 1) :]
    returns = asset_returns_frame(tail)
    corr = _engine(correlation_matrix, returns)
    return StockCorrelationResponse(
        tickers=[str(c) for c in prices.columns],
        matrix=[[float(value) for value in row] for row in corr.to_numpy(dtype=float)],
        window=window,
        as_of=_to_date(tail.index[-1]),
    )


async def run_stock_correlation(
    session: AsyncSession,
    payload: StockCorrelationRequest,
) -> StockCorrelationResponse:
    """Orchestrate the holdings correlation matrix over a trailing window.

    ``end_date`` defaults to today; the effective window end (``as_of``) is
    the latest trading day COMMON to all holdings at or before it. Closes are
    read from ``end - lookback_pad(window + 1)`` so the trailing window is
    covered with calendar slack for weekends/holidays.
    """
    end = payload.end_date or dt.date.today()
    pad_start = end - dt.timedelta(days=lookback_pad_days(payload.window + 1))
    _, _, series_by_ticker = await _load_portfolio_prices(
        session, payload.portfolio_id, pad_start, end
    )
    return assemble_stock_correlation(series_by_ticker, window=payload.window)


class _VersionedStockCorrelation(BaseModel):
    """Payload de cache: request + hash de versão do portfólio (invalida ao editar)."""

    request: StockCorrelationRequest
    portfolio_version: str


@cached_result("stat_stock_correlation")
async def _run_stock_correlation_cached(
    session: AsyncSession, payload: _VersionedStockCorrelation
) -> StockCorrelationResponse:
    return await run_stock_correlation(session, payload.request)
