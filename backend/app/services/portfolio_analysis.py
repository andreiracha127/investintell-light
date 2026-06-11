"""Assembly of the render-ready payload for POST /portfolio/analysis.

Pure pandas adapter between per-ticker DB price series and the response
schema — no database access, no FastAPI, no I/O. The route loads adjusted
closes per ticker over the resolved window and calls
:func:`assemble_portfolio_analysis`.

Window contract: the route resolves the query window (end = the common last
date across tickers; start = end minus the range preset, or the LATEST
inception for MAX). This module inner-joins the per-ticker series onto the
dates where ALL position tickers have data — the joined frame's first/last
dates are echoed as ``params.start_date`` / ``params.end_date`` (the window
that was actually analyzed). No rolling-warm-up pad is needed: this payload
carries no rolling series.

Every statistic is computed by the F2/F3 engine functions (one engine —
nothing is reimplemented here). Two-views semantics (replay vs
decomposition) are documented in ``app.analytics.portfolio``.

Scale contract (project-wide): all fractional quantities are decimal
fractions (0.05 = 5%), never 0-100.
"""

from collections.abc import Mapping

import pandas as pd

from app.analytics import (
    DEFAULT_INITIAL_NAV,
    MIN_IN_RANGE_RETURNS,
    align_returns,
    annualized_volatility,
    asset_returns_frame,
    best_worst_day,
    beta,
    correlation,
    correlation_matrix,
    diversification_ratio,
    historical_cvar,
    historical_var,
    max_drawdown,
    portfolio_nav,
    portfolio_returns,
    return_histogram,
    risk_contributions,
    simple_returns,
    total_return,
    weights_to_quantities,
)
from app.analytics._validation import to_date as _to_date
from app.schemas.analysis import DatedValue, DrawdownOut, HistogramOut, RangeKey
from app.schemas.portfolio_analysis import (
    AllocationOut,
    AllocationPosition,
    BenchmarkComparison,
    CorrelationMatrixOut,
    PortfolioAnalysisResponse,
    PortfolioMode,
    PortfolioParams,
    PortfolioStats,
    RiskContributionOut,
)
from app.services._series import (
    rebased_cumulative,
    rebased_cumulative_weekly,
    resample_weekly,
    series_points,
)
from app.services.stock_analysis import InsufficientDataError, PayloadTooLargeError

_HISTOGRAM_BINS = 20


def _join_prices(series_by_ticker: Mapping[str, pd.Series]) -> pd.DataFrame:
    """Inner-join per-ticker adjusted-close series on their common dates.

    The result has one column per ticker (insertion order preserved) and only
    the dates where ALL tickers have data.
    """
    columns = [series.rename(ticker) for ticker, series in series_by_ticker.items()]
    return pd.concat(columns, axis=1, join="inner")


def _shortest_history_ticker(series_by_ticker: Mapping[str, pd.Series]) -> str:
    """Ticker whose history starts LATEST (the one squeezing the common window)."""
    return max(
        series_by_ticker,
        key=lambda t: (
            series_by_ticker[t].index[0]
            if len(series_by_ticker[t])
            else pd.Timestamp.max
        ),
    )


def _resolve_allocation(
    prices: pd.DataFrame,
    *,
    mode: PortfolioMode,
    weights: Mapping[str, float] | None,
    quantities: Mapping[str, float] | None,
) -> tuple[dict[str, float], dict[str, float], float]:
    """Resolve (effective_weights, quantities, initial_nav) at the first date.

    mode='weights': weights are renormalized to sum exactly to 1 (the API has
    already enforced the 1 +/- 1e-3 tolerance; renormalizing satisfies the
    engine's 1e-6 guard and the renormalized values are what gets echoed) and
    converted to synthetic quantities at the first date against the notional
    DEFAULT_INITIAL_NAV.

    mode='quantities': quantities are taken as given; effective weights are
    the initial-date value weights ``qty_i * price_i(first) / NAV(first)``.
    """
    first_row = prices.iloc[0]
    if mode == "weights":
        if weights is None:
            raise ValueError("mode='weights' requires weights")
        total = float(sum(weights.values()))
        effective = {ticker: float(w) / total for ticker, w in weights.items()}
        qty = weights_to_quantities(first_row, effective, DEFAULT_INITIAL_NAV)
        return effective, qty, DEFAULT_INITIAL_NAV

    if quantities is None:
        raise ValueError("mode='quantities' requires quantities")
    values = {
        ticker: float(q) * float(first_row[ticker]) for ticker, q in quantities.items()
    }
    initial_nav = float(sum(values.values()))
    if not initial_nav > 0:
        raise ValueError("portfolio initial value must be > 0")
    effective = {ticker: value / initial_nav for ticker, value in values.items()}
    return effective, {t: float(q) for t, q in quantities.items()}, initial_nav


def _benchmark_comparison(
    nav: pd.Series,
    aligned_port: pd.Series,
    aligned_bench: pd.Series,
    range_key: RangeKey,
) -> BenchmarkComparison:
    """Build the benchmark comparison series aligned to the same grid as nav.

    Single-grid contract: all three line series (nav, comparison.portfolio,
    comparison.benchmark) share identical first/last dates.

    ``aligned_port`` and ``aligned_bench`` are *return* series — their first
    index entry is the second price date of the aligned grid.  To achieve the
    single-grid contract we need the rebase point (first price date, 0.0) to
    coincide with nav's first date.  We identify that date as the nav index
    entry that immediately precedes ``aligned_port.index[0]``, prepend it as
    a synthetic 0-return entry, and pass the extended series to the rebasing
    helpers.  This leaves nav[0] == initial_nav intact.

    Stats (beta, correlation, drawdown, …) are computed by the caller on the
    original ``aligned_port``/``aligned_bench`` — unmodified.
    """
    # Find the nav date that is one step before aligned_port.index[0].
    # When the benchmark and positions share the same start, this is
    # prices.index[0] (the initial NAV day).  When the benchmark starts later,
    # this is the benchmark's first price date (within the nav index).
    first_return_date = aligned_port.index[0]
    nav_dates_before = nav.index[nav.index < first_return_date]
    if len(nav_dates_before):
        rebase_date = nav_dates_before[-1]
        # Prepend a zero-return at the rebase date so rebased_cumulative emits
        # (rebase_date, 0.0) as its first point — matching nav[0]'s date.
        zero_return = pd.Series([0.0], index=[rebase_date])
        port_ext = pd.concat([zero_return, aligned_port])
        bench_ext = pd.concat([zero_return, aligned_bench])
    else:
        # No nav date precedes the first return — fall back to the standard
        # rebasing (rebased_cumulative already emits the first return date).
        port_ext = aligned_port
        bench_ext = aligned_bench

    if range_key == "MAX":
        return BenchmarkComparison(
            portfolio=rebased_cumulative_weekly(port_ext),
            benchmark=rebased_cumulative_weekly(bench_ext),
        )
    return BenchmarkComparison(
        portfolio=rebased_cumulative(port_ext),
        benchmark=rebased_cumulative(bench_ext),
    )


def assemble_portfolio_analysis(
    series_by_ticker: Mapping[str, pd.Series],
    benchmark_adj_close: pd.Series,
    *,
    mode: PortfolioMode,
    weights: Mapping[str, float] | None,
    quantities: Mapping[str, float] | None,
    benchmark: str,
    range_key: RangeKey,
    max_points: int,
) -> PortfolioAnalysisResponse:
    """Assemble the full portfolio analysis payload from per-ticker price series.

    Args:
        series_by_ticker: Date-indexed ADJUSTED-close series per position
            ticker over the route-resolved window (insertion order is the
            payload order).
        benchmark_adj_close: Date-indexed adjusted closes for the benchmark
            over the same window.
        mode / weights / quantities: validated request allocation — exactly
            one of ``weights`` / ``quantities`` is set, matching ``mode``,
            keyed by the position tickers.
        benchmark / range_key: resolved request parameters (echoed in params).
        max_points: hard cap on the longest emitted line series (fail loud).

    Raises:
        InsufficientDataError: too few common trading days across the
            position tickers (the offending ticker is named) or too few
            aligned days with the benchmark.
        PayloadTooLargeError: a line series would exceed ``max_points``.
    """
    prices = _join_prices(series_by_ticker)
    if len(prices) < MIN_IN_RANGE_RETURNS + 1:
        offender = _shortest_history_ticker(series_by_ticker)
        offender_series = series_by_ticker[offender]
        inception = (
            f" (history starts {_to_date(offender_series.index[0]).isoformat()})"
            if len(offender_series)
            else " (no price history)"
        )
        raise InsufficientDataError(
            f"Only {len(prices)} trading days are shared by ALL position tickers — "
            f"at least {MIN_IN_RANGE_RETURNS + 1} are required. {offender} has the "
            f"shortest history{inception}. Use a wider range or drop that position."
        )

    effective_weights, qty, initial_nav = _resolve_allocation(
        prices, mode=mode, weights=weights, quantities=quantities
    )
    first_row = prices.iloc[0]
    allocation = AllocationOut(
        positions=[
            AllocationPosition(
                ticker=ticker,
                weight=effective_weights[ticker],
                initial_value=qty[ticker] * float(first_row[ticker]),
            )
            for ticker in prices.columns
        ],
        initial_nav=initial_nav,
    )

    # REPLAY view: buy-and-hold NAV and its daily returns (one engine).
    nav = portfolio_nav(prices, qty)
    port_returns = portfolio_returns(prices, qty)

    # Benchmark comparison: align portfolio and benchmark returns on their
    # common dates, then rebase both cumulative series to 0 at the same first
    # date (same approach as F2.2).
    if len(benchmark_adj_close) < 2:
        raise InsufficientDataError(
            f"Only {len(benchmark_adj_close)} price rows available for benchmark "
            f"{benchmark} — not enough history to compute returns."
        )
    bench_returns = simple_returns(benchmark_adj_close)
    try:
        aligned_port, aligned_bench = align_returns(port_returns, bench_returns)
    except ValueError as exc:
        raise InsufficientDataError(
            f"The portfolio and benchmark {benchmark} share too few trading days: {exc}"
        ) from exc
    if len(aligned_port) < MIN_IN_RANGE_RETURNS:
        raise InsufficientDataError(
            f"Only {len(aligned_port)} trading days shared by the portfolio and "
            f"benchmark {benchmark} — at least {MIN_IN_RANGE_RETURNS} are required "
            "for beta/correlation."
        )

    # Single-grid contract: all three line series (nav, comparison.portfolio,
    # comparison.benchmark) MUST share the same date grid so the frontend can
    # align them on a single x-axis without a join step.
    #
    # Grid choice: the nav's full position-price grid, trimmed to the dates
    # that the benchmark also covers.  Concretely:
    #   - `nav` starts at prices.index[0] (the first position price date).
    #   - `aligned_port/bench` are *return* series; their index starts at the
    #     second date of the aligned price grid.
    #   - We prepend the first aligned-price date (one step before
    #     aligned_port.index[0]) to the return series so that
    #     `rebased_cumulative` emits a (first_price_date, 0.0) rebase point.
    #   - `nav` is then sliced to the dates in the extended return + rebase
    #     point set — i.e. the aligned price dates.
    #
    # This preserves nav[0] == initial_nav (the initial buy-in value) AND
    # ensures all three series share identical first/last dates.
    #
    # Stats and drawdown stay computed on the FULL position-grid nav (before
    # any benchmark-alignment slice) — they describe the portfolio, not the
    # comparison chart.
    comparison = _benchmark_comparison(nav, aligned_port, aligned_bench, range_key)

    # Emit nav sliced to the same date grid as comparison (the aligned price
    # dates, starting at the rebase date).  comparison.portfolio is already
    # on this grid (daily or weekly); we build nav_aligned from the same
    # underlying aligned index so all three series share first/last dates.
    #
    # Reconstruct the aligned price-level index: rebase_date + aligned_port.index.
    first_return_date = aligned_port.index[0]
    nav_dates_before = nav.index[nav.index < first_return_date]
    aligned_price_dates = (
        nav.index[nav.index >= nav_dates_before[-1]]
        if len(nav_dates_before)
        else nav.index[nav.index >= first_return_date]
    )
    nav_aligned = nav.loc[nav.index.isin(aligned_price_dates)]

    # For range MAX the line series are bounded to the W-FRI weekly grid.
    if range_key == "MAX":
        nav_points = series_points(resample_weekly(nav_aligned))
    else:
        nav_points = series_points(nav_aligned)

    longest = max(len(nav_points), len(comparison.portfolio), len(comparison.benchmark))
    if longest > max_points:
        raise PayloadTooLargeError(
            f"Range {range_key}: longest line series has {longest} points, "
            f"exceeding the maximum of {max_points}."
        )

    # DECOMPOSITION view: per-asset returns at the effective initial weights.
    returns_frame = asset_returns_frame(prices)
    corr = correlation_matrix(returns_frame)
    contributions = risk_contributions(returns_frame, effective_weights)

    drawdown = max_drawdown(nav)
    best_worst = best_worst_day(port_returns)
    stats = PortfolioStats(
        annualized_volatility=annualized_volatility(port_returns),
        var_95=historical_var(port_returns, confidence=0.95),
        var_99=historical_var(port_returns, confidence=0.99),
        cvar_95=historical_cvar(port_returns, confidence=0.95),
        total_return=total_return(port_returns),
        beta=beta(aligned_port, aligned_bench),
        correlation=correlation(aligned_port, aligned_bench),
        diversification_ratio=diversification_ratio(returns_frame, effective_weights),
        max_drawdown=DrawdownOut(
            depth=drawdown.depth,
            peak_date=drawdown.peak_date,
            trough_date=drawdown.trough_date,
        ),
        best_day=DatedValue(date=best_worst.best_date, value=best_worst.best_return),
        worst_day=DatedValue(date=best_worst.worst_date, value=best_worst.worst_return),
    )

    histogram = return_histogram(port_returns, bins=_HISTOGRAM_BINS)

    tickers = [str(c) for c in prices.columns]
    return PortfolioAnalysisResponse(
        params=PortfolioParams(
            mode=mode,
            range=range_key,
            benchmark=benchmark,
            start_date=_to_date(prices.index[0]),
            end_date=_to_date(prices.index[-1]),
            initial_nav=initial_nav,
        ),
        allocation=allocation,
        nav=nav_points,
        benchmark_comparison=comparison,
        stats=stats,
        correlation_matrix=CorrelationMatrixOut(
            tickers=tickers,
            # corr's row/column order is the prices column order (= tickers).
            matrix=[[float(value) for value in row] for row in corr.to_numpy(dtype=float)],
        ),
        risk_contributions=[
            RiskContributionOut(ticker=ticker, contribution=contributions[ticker])
            for ticker in tickers
        ],
        histogram=HistogramOut(
            bin_edges=histogram.bin_edges,
            counts=histogram.counts,
            counts_normalized=histogram.counts_normalized,
        ),
    )
