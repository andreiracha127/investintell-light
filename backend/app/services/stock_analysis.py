"""Assembly of the render-ready payload for GET /stocks/{ticker}/analysis.

Pure pandas adapter between DB price rows and the response schema — no
database access, no FastAPI, no I/O. The route loads padded price frames and
calls :func:`assemble_analysis`.

Padding contract: the input frames cover ``[start - lookback_pad, end]``.
The pad exists ONLY to warm up rolling windows so rolling series cover the
visible range from (approximately) its first trading day. It never leaks
into point statistics:

- header / candles / max_drawdown use PRICES with ``date >= start``;
- stats / histogram / cumulative returns use ONLY RETURNS dated strictly
  AFTER ``start``;
- rolling series are computed on the full padded returns, then SLICED to
  ``date > start`` with NaN rows dropped.

Scale contract (project-wide): all fractional quantities are decimal
fractions (0.05 = 5%), never 0-100.
"""

import datetime as dt
import math
from collections.abc import Hashable, Iterable, Mapping

import pandas as pd
from sqlalchemy.ext.asyncio import AsyncSession

from app.analytics import (
    MIN_IN_RANGE_RETURNS,
    align_returns,
    annualized_volatility,
    best_worst_day,
    beta,
    correlation,
    historical_cvar,
    historical_var,
    max_drawdown,
    return_histogram,
    rolling_beta,
    rolling_correlation,
    rolling_volatility,
    simple_returns,
    total_return,
)
from app.analytics._validation import to_date as _to_date
from app.schemas.analysis import (
    AnalysisHeader,
    AnalysisParams,
    AnalysisStats,
    Candle,
    CumulativeReturns,
    DatedValue,
    DrawdownOut,
    HistogramOut,
    RangeKey,
    StockAnalysisResponse,
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
    series_points as _series_points,
)

import app.services.series_sql as series_sql

_HISTOGRAM_BINS = 20

# Display ranges whose candle/line series are weekly-downsampled to bound the
# payload (mirrors timeseries._INTERVAL_BY_RANGE: 5Y and MAX → weekly grid).
# Statistics are ALWAYS computed on the daily base and are unaffected.
_WEEKLY_DISPLAY_RANGES = frozenset({"5Y", "MAX"})

_PRICE_COLUMNS = ["open", "high", "low", "close", "volume", "adj_close"]

# Aggregation rules for weekly (W-FRI) candle resampling on range MAX.
_WEEKLY_AGG: Mapping[Hashable, str] = {
    "open": "first",
    "high": "max",
    "low": "min",
    "close": "last",
    "volume": "sum",
}


class StockAnalysisError(Exception):
    """Base for assembly failures the route maps to HTTP 422 (fail loud)."""


class InsufficientDataError(StockAnalysisError):
    """Not enough price history to compute the full stats block — never partial stats."""


class PayloadTooLargeError(StockAnalysisError):
    """The candle list would exceed the configured maximum point count."""


def lookback_pad_days(window: int) -> int:
    """CALENDAR days that safely cover *window* TRADING days before the range start.

    ``ceil(window * 7/5)`` converts trading days to calendar days; +15 absorbs
    holidays so rolling series are warm from the first visible day.
    """
    return math.ceil(window * 7 / 5) + 15


def build_price_frame(
    records: Iterable[tuple[dt.date, float, float, float, float, int, float]],
) -> pd.DataFrame:
    """Build a date-indexed OHLCV+adj_close frame from DB row tuples.

    ``records`` are ``(date, open, high, low, close, volume, adj_close)``
    tuples; the result is sorted by its DatetimeIndex.
    """
    frame = pd.DataFrame(list(records), columns=["date", *_PRICE_COLUMNS])
    frame["date"] = pd.to_datetime(frame["date"])
    return frame.set_index("date").sort_index()


def build_adj_close_series(records: Iterable[tuple[dt.date, float]]) -> pd.Series:
    """Build a date-indexed adjusted-close series from DB row tuples."""
    frame = pd.DataFrame(list(records), columns=["date", "adj_close"])
    frame["date"] = pd.to_datetime(frame["date"])
    return frame.set_index("date")["adj_close"].sort_index()


def _weekly_candles(frame: pd.DataFrame) -> pd.DataFrame:
    """Resample daily candles to weekly W-FRI buckets (bounded payload for MAX).

    open=first, high=max, low=min, close=last, volume=sum; weeks with no
    trading days are dropped. The emitted date is the bucket's Friday label.
    """
    weekly = frame.resample("W-FRI").agg(_WEEKLY_AGG)
    return weekly.dropna(subset=["open"])


def _candles(frame: pd.DataFrame) -> list[Candle]:
    return [
        Candle(
            date=_to_date(label),
            open=float(row["open"]),
            high=float(row["high"]),
            low=float(row["low"]),
            close=float(row["close"]),
            volume=int(row["volume"]),
        )
        for label, row in frame.iterrows()
    ]


def assemble_analysis(
    asset: pd.DataFrame,
    benchmark_adj_close: pd.Series,
    *,
    ticker: str,
    name: str | None,
    benchmark: str,
    range_key: RangeKey,
    window: int,
    start: dt.date,
    end: dt.date,
    max_candles: int,
) -> StockAnalysisResponse:
    """Assemble the full analysis payload from padded price data.

    Args:
        asset: Date-indexed frame with open/high/low/close/volume/adj_close
            covering ``[start - lookback_pad, end]`` (pad = rolling warm-up only).
        benchmark_adj_close: Date-indexed adjusted closes for the benchmark
            over the same padded window.
        ticker / name / benchmark / range_key / window / start / end: resolved
            request parameters (echoed in ``params``).
        max_candles: hard cap on the emitted candle count (fail loud).

    Raises:
        InsufficientDataError: too little history for the full stats block.
        PayloadTooLargeError: candle list would exceed ``max_candles``.
    """
    if len(asset) < 2:
        raise InsufficientDataError(
            f"Only {len(asset)} price rows available for {ticker} — "
            "not enough history to compute returns."
        )
    if len(benchmark_adj_close) < 2:
        raise InsufficientDataError(
            f"Only {len(benchmark_adj_close)} price rows available for benchmark "
            f"{benchmark} — not enough history to compute returns."
        )

    start_ts = pd.Timestamp(start)

    # Returns from ADJUSTED closes over the padded window.
    asset_returns = simple_returns(asset["adj_close"])
    bench_returns = simple_returns(benchmark_adj_close)

    # In-range slice: ONLY returns dated strictly after `start` feed the
    # stats/histogram/cumulative blocks (the pad is rolling warm-up only).
    in_range_returns = asset_returns[asset_returns.index > start_ts]
    if len(in_range_returns) < MIN_IN_RANGE_RETURNS:
        raise InsufficientDataError(
            f"Only {len(in_range_returns)} in-range daily returns for {ticker} over range "
            f"{range_key} — at least {MIN_IN_RANGE_RETURNS} are required for the stats "
            "block. Use a wider range or a ticker with more history."
        )

    try:
        aligned_asset, aligned_bench = align_returns(asset_returns, bench_returns)
    except ValueError as exc:
        raise InsufficientDataError(
            f"{ticker} and benchmark {benchmark} share too few trading days: {exc}"
        ) from exc

    in_mask = aligned_asset.index > start_ts
    aligned_in_asset = aligned_asset[in_mask]
    aligned_in_bench = aligned_bench[in_mask]
    if len(aligned_in_asset) < MIN_IN_RANGE_RETURNS:
        raise InsufficientDataError(
            f"Only {len(aligned_in_asset)} in-range trading days shared by {ticker} and "
            f"benchmark {benchmark} — at least {MIN_IN_RANGE_RETURNS} are required for "
            "beta/correlation."
        )
    if len(asset_returns) < window or len(aligned_asset) < window:
        raise InsufficientDataError(
            f"Rolling window of {window} trading days exceeds the available padded history "
            f"({len(asset_returns)} asset returns, {len(aligned_asset)} aligned with "
            f"{benchmark}). Reduce the window or use a ticker/benchmark with more history."
        )

    # Header: RAW closes of the last two trading days (end == last DB date,
    # so the padded tail and the visible tail coincide).
    last_close = float(asset["close"].iloc[-1])
    prev_close = float(asset["close"].iloc[-2])
    change = last_close - prev_close
    header = AnalysisHeader(
        ticker=ticker,
        name=name,
        last_close=last_close,
        prev_close=prev_close,
        change=change,
        change_pct=change / prev_close,
        as_of=_to_date(asset.index[-1]),
    )

    # Candles: RAW in-range prices; weekly resample bounds the 5Y/MAX payload.
    weekly_display = range_key in _WEEKLY_DISPLAY_RANGES
    visible = asset[asset.index >= start_ts]
    candle_frame = _weekly_candles(visible) if weekly_display else visible
    if len(candle_frame) > max_candles:
        raise PayloadTooLargeError(
            f"Range {range_key} for {ticker} would emit {len(candle_frame)} candles, "
            f"exceeding the maximum of {max_candles}."
        )

    # Cumulative returns: aligned grid, sliced in-range, both rebased to 0
    # on the same first in-range date.
    # For 5Y/MAX, resample to W-FRI so the x-axis aligns with the weekly candles.
    if weekly_display:
        cumulative = CumulativeReturns(
            asset=_rebased_cumulative_weekly(aligned_in_asset),
            benchmark=_rebased_cumulative_weekly(aligned_in_bench),
        )
    else:
        cumulative = CumulativeReturns(
            asset=_rebased_cumulative(aligned_in_asset),
            benchmark=_rebased_cumulative(aligned_in_bench),
        )

    # Rolling series: warm up on the padded returns, then slice to the
    # visible range and drop NaN rows (leading min_periods warm-up and any
    # undefined windows). For 5Y/MAX, resample to W-FRI to bound the payload
    # and align the x-axis with the candle grid.
    def _sliced(series: pd.Series) -> list[tuple[dt.date, float]]:
        daily = series[series.index > start_ts].dropna()
        return _series_points(_resample_weekly(daily) if weekly_display else daily)

    rolling_vol_points = _sliced(rolling_volatility(asset_returns, window))
    rolling_beta_points = _sliced(rolling_beta(asset_returns, bench_returns, window))
    rolling_corr_points = _sliced(rolling_correlation(asset_returns, bench_returns, window))

    # Bound assertion: "bounded everything" — the longest line series must not
    # exceed the candle budget (same price_series_max_points cap).
    _all_line_series = [
        cumulative.asset,
        cumulative.benchmark,
        rolling_vol_points,
        rolling_beta_points,
        rolling_corr_points,
    ]
    longest = max(len(s) for s in _all_line_series)
    if longest > max_candles:
        raise PayloadTooLargeError(
            f"Range {range_key} for {ticker}: longest line series has {longest} points, "
            f"exceeding the maximum of {max_candles}."
        )

    histogram = return_histogram(in_range_returns, bins=_HISTOGRAM_BINS)

    drawdown = max_drawdown(visible["adj_close"])
    best_worst = best_worst_day(in_range_returns)
    stats = AnalysisStats(
        annualized_volatility=annualized_volatility(in_range_returns),
        var_95=historical_var(in_range_returns, confidence=0.95),
        var_99=historical_var(in_range_returns, confidence=0.99),
        cvar_95=historical_cvar(in_range_returns, confidence=0.95),
        total_return=total_return(in_range_returns),
        beta=beta(aligned_in_asset, aligned_in_bench),
        correlation=correlation(aligned_in_asset, aligned_in_bench),
        max_drawdown=DrawdownOut(
            depth=drawdown.depth,
            peak_date=drawdown.peak_date,
            trough_date=drawdown.trough_date,
        ),
        best_day=DatedValue(date=best_worst.best_date, value=best_worst.best_return),
        worst_day=DatedValue(date=best_worst.worst_date, value=best_worst.worst_return),
    )

    return StockAnalysisResponse(
        params=AnalysisParams(
            range=range_key,
            benchmark=benchmark,
            window=window,
            start_date=start,
            end_date=end,
        ),
        header=header,
        candles=_candles(candle_frame),
        cumulative_returns=cumulative,
        rolling_volatility=rolling_vol_points,
        rolling_beta=rolling_beta_points,
        rolling_correlation=rolling_corr_points,
        histogram=HistogramOut(
            bin_edges=histogram.bin_edges,
            counts=histogram.counts,
            counts_normalized=histogram.counts_normalized,
        ),
        stats=stats,
    )


async def assemble_analysis_sql(
    session: AsyncSession,
    asset: pd.DataFrame,
    benchmark_adj_close: pd.Series,
    *,
    ticker: str,
    name: str | None,
    benchmark: str,
    range_key: RangeKey,
    window: int,
    start: dt.date,
    end: dt.date,
    max_candles: int,
) -> StockAnalysisResponse:
    """SQL-backed analysis: rolling vol/beta/corr, histogram, VaR(95/99), CVaR(95)
    come from fn_* functions; candles/cumulative/header/scalars stay in Python
    (NOT in the §8 series-function set). Validates the same gates as
    assemble_analysis before reading SQL series.

    The Python-kept scalars (annualized_volatility, total_return, beta,
    correlation, max_drawdown peak/trough, best/worst day) and the
    candles/cumulative-return series remain pandas — they are intentionally
    outside the moved series set. The legacy stock path emits NO drawdown LINE
    series, so fn_drawdown is not used here.
    """
    # --- validation + returns (verbatim from assemble_analysis) ---
    if len(asset) < 2:
        raise InsufficientDataError(
            f"Only {len(asset)} price rows available for {ticker} — "
            "not enough history to compute returns."
        )
    if len(benchmark_adj_close) < 2:
        raise InsufficientDataError(
            f"Only {len(benchmark_adj_close)} price rows available for benchmark "
            f"{benchmark} — not enough history to compute returns."
        )

    start_ts = pd.Timestamp(start)
    asset_returns = simple_returns(asset["adj_close"])
    bench_returns = simple_returns(benchmark_adj_close)

    in_range_returns = asset_returns[asset_returns.index > start_ts]
    if len(in_range_returns) < MIN_IN_RANGE_RETURNS:
        raise InsufficientDataError(
            f"Only {len(in_range_returns)} in-range daily returns for {ticker} over range "
            f"{range_key} — at least {MIN_IN_RANGE_RETURNS} are required for the stats "
            "block. Use a wider range or a ticker with more history."
        )

    try:
        aligned_asset, aligned_bench = align_returns(asset_returns, bench_returns)
    except ValueError as exc:
        raise InsufficientDataError(
            f"{ticker} and benchmark {benchmark} share too few trading days: {exc}"
        ) from exc

    in_mask = aligned_asset.index > start_ts
    aligned_in_asset = aligned_asset[in_mask]
    aligned_in_bench = aligned_bench[in_mask]
    if len(aligned_in_asset) < MIN_IN_RANGE_RETURNS:
        raise InsufficientDataError(
            f"Only {len(aligned_in_asset)} in-range trading days shared by {ticker} and "
            f"benchmark {benchmark} — at least {MIN_IN_RANGE_RETURNS} are required for "
            "beta/correlation."
        )
    if len(asset_returns) < window or len(aligned_asset) < window:
        raise InsufficientDataError(
            f"Rolling window of {window} trading days exceeds the available padded history "
            f"({len(asset_returns)} asset returns, {len(aligned_asset)} aligned with "
            f"{benchmark}). Reduce the window or use a ticker/benchmark with more history."
        )

    # Header (verbatim).
    last_close = float(asset["close"].iloc[-1])
    prev_close = float(asset["close"].iloc[-2])
    change = last_close - prev_close
    header = AnalysisHeader(
        ticker=ticker,
        name=name,
        last_close=last_close,
        prev_close=prev_close,
        change=change,
        change_pct=change / prev_close,
        as_of=_to_date(asset.index[-1]),
    )

    # Candles (verbatim).
    weekly_display = range_key in _WEEKLY_DISPLAY_RANGES
    visible = asset[asset.index >= start_ts]
    candle_frame = _weekly_candles(visible) if weekly_display else visible
    if len(candle_frame) > max_candles:
        raise PayloadTooLargeError(
            f"Range {range_key} for {ticker} would emit {len(candle_frame)} candles, "
            f"exceeding the maximum of {max_candles}."
        )

    # Cumulative returns (verbatim).
    if weekly_display:
        cumulative = CumulativeReturns(
            asset=_rebased_cumulative_weekly(aligned_in_asset),
            benchmark=_rebased_cumulative_weekly(aligned_in_bench),
        )
    else:
        cumulative = CumulativeReturns(
            asset=_rebased_cumulative(aligned_in_asset),
            benchmark=_rebased_cumulative(aligned_in_bench),
        )

    # Rolling series via SQL (the moved set). Slice strict + weekly downsample
    # without pandas, mirroring the legacy `date > start` + W-FRI semantics.
    vol_full, _ = await series_sql.rolling_metrics_points(
        session, ticker=ticker, window=window, start=start, end=end
    )
    beta_full, corr_full = await series_sql.rolling_beta_corr_points(
        session, ticker=ticker, benchmark=benchmark, window=window, start=start, end=end
    )

    def _sl(points: list[series_sql.SeriesPoint]) -> list[series_sql.SeriesPoint]:
        out = series_sql.slice_strict(points, start)
        return series_sql.week_downsample(out) if weekly_display else out

    rolling_vol_points = _sl(vol_full)
    rolling_beta_points = _sl(beta_full)
    rolling_corr_points = _sl(corr_full)

    _all_line_series = [
        cumulative.asset,
        cumulative.benchmark,
        rolling_vol_points,
        rolling_beta_points,
        rolling_corr_points,
    ]
    longest = max(len(s) for s in _all_line_series)
    if longest > max_candles:
        raise PayloadTooLargeError(
            f"Range {range_key} for {ticker}: longest line series has {longest} points, "
            f"exceeding the maximum of {max_candles}."
        )

    histogram = await series_sql.histogram_out(
        session, ticker=ticker, bins=_HISTOGRAM_BINS, start=start, end=end
    )
    var_95, cvar_95 = await series_sql.var_cvar(
        session, ticker=ticker, level=0.95, start=start, end=end
    )
    var_99, _ = await series_sql.var_cvar(
        session, ticker=ticker, level=0.99, start=start, end=end
    )

    # Scalars that stay in Python (verbatim from assemble_analysis).
    drawdown = max_drawdown(visible["adj_close"])
    best_worst = best_worst_day(in_range_returns)
    stats = AnalysisStats(
        annualized_volatility=annualized_volatility(in_range_returns),
        var_95=var_95,
        var_99=var_99,
        cvar_95=cvar_95,
        total_return=total_return(in_range_returns),
        beta=beta(aligned_in_asset, aligned_in_bench),
        correlation=correlation(aligned_in_asset, aligned_in_bench),
        max_drawdown=DrawdownOut(
            depth=drawdown.depth,
            peak_date=drawdown.peak_date,
            trough_date=drawdown.trough_date,
        ),
        best_day=DatedValue(date=best_worst.best_date, value=best_worst.best_return),
        worst_day=DatedValue(date=best_worst.worst_date, value=best_worst.worst_return),
    )

    return StockAnalysisResponse(
        params=AnalysisParams(
            range=range_key,
            benchmark=benchmark,
            window=window,
            start_date=start,
            end_date=end,
        ),
        header=header,
        candles=_candles(candle_frame),
        cumulative_returns=cumulative,
        rolling_volatility=rolling_vol_points,
        rolling_beta=rolling_beta_points,
        rolling_correlation=rolling_corr_points,
        histogram=histogram,
        stats=stats,
    )
