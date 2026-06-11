"""Unit tests for app/services/stock_analysis.py — synthetic frames, no DB.

Verifies the padding contract (pad feeds rolling warm-up ONLY), the weekly
resample for range MAX, cumulative-series rebasing/alignment, rolling
slice+NaN-drop, and the loud insufficient-data / payload-cap failure paths.
"""

import datetime as dt

import numpy as np
import pandas as pd
import pytest

from app.services.stock_analysis import (
    InsufficientDataError,
    PayloadTooLargeError,
    assemble_analysis,
    build_adj_close_series,
    build_price_frame,
    lookback_pad_days,
)

WINDOW = 21


def _price_frame(dates: pd.DatetimeIndex, closes: np.ndarray) -> pd.DataFrame:
    """OHLCV+adj frame where raw close == adj close (no corporate actions)."""
    return pd.DataFrame(
        {
            "open": closes * 0.99,
            "high": closes * 1.02,
            "low": closes * 0.98,
            "close": closes,
            "volume": np.full(len(dates), 1_000, dtype=np.int64),
            "adj_close": closes,
        },
        index=dates,
    )


def _walk(n: int, seed: int, daily_vol: float = 0.01) -> np.ndarray:
    rng = np.random.default_rng(seed)
    returns = rng.normal(0.0004, daily_vol, n)
    return 100.0 * np.cumprod(1 + returns)


def _padded_inputs(
    n_days: int = 400, *, crash_in_pad: bool = False
) -> tuple[pd.DataFrame, pd.Series, dt.date, dt.date]:
    """Business-day data; visible range = last 252 trading days (~1Y).

    Returns (asset_frame, benchmark_series, start, end). The pad is everything
    before `start`. With ``crash_in_pad`` the asset loses 50% on a pad day —
    stats must never see it.
    """
    dates = pd.bdate_range("2024-01-01", periods=n_days)
    closes = _walk(n_days, seed=1)
    if crash_in_pad:
        closes[40:] = closes[40:] * 0.5  # -50% day deep inside the pad
    asset = _price_frame(dates, closes)
    benchmark = pd.Series(_walk(n_days, seed=2), index=dates, name="adj_close")
    start = dates[-252].date() - dt.timedelta(days=1)  # 252 trading days visible
    end = dates[-1].date()
    return asset, benchmark, start, end


def _assemble(asset, bench_series, start, end, **overrides):  # type: ignore[no-untyped-def]
    kwargs = dict(
        ticker="TEST",
        name="Test Corp",
        benchmark="BENCH",
        range_key="1Y",
        window=WINDOW,
        start=start,
        end=end,
        max_candles=7000,
    )
    kwargs.update(overrides)
    return assemble_analysis(asset, bench_series, **kwargs)


# ---------------------------------------------------------------------------
# In-range slicing: the pad never leaks into point statistics
# ---------------------------------------------------------------------------


def test_stats_ignore_pad_returns() -> None:
    asset, benchmark, start, end = _padded_inputs(crash_in_pad=True)
    payload = _assemble(asset, benchmark, start, end)

    # The -50% crash lives in the pad; worst day must be in-range and mild.
    assert payload.stats.worst_day.date > start
    assert payload.stats.worst_day.value > -0.2
    # Histogram edges must not stretch to the crash either.
    assert payload.histogram.bin_edges[0] > -0.2
    # Drawdown is computed on in-range adjusted closes only.
    assert payload.stats.max_drawdown.peak_date >= start
    assert payload.stats.max_drawdown.depth > -0.5


def test_stats_match_manual_in_range_computation() -> None:
    asset, benchmark, start, end = _padded_inputs()
    payload = _assemble(asset, benchmark, start, end)

    returns = asset["adj_close"].pct_change().dropna()
    in_range = returns[returns.index > pd.Timestamp(start)]
    expected_total = float((1 + in_range).prod()) - 1.0
    assert payload.stats.total_return == pytest.approx(expected_total)
    expected_vol = float(in_range.std(ddof=1)) * np.sqrt(252)
    assert payload.stats.annualized_volatility == pytest.approx(expected_vol)


def test_var99_at_least_var95_in_assembled_payload() -> None:
    asset, benchmark, start, end = _padded_inputs()
    payload = _assemble(asset, benchmark, start, end)
    assert payload.stats.var_99 >= payload.stats.var_95
    assert payload.stats.cvar_95 >= payload.stats.var_95


def test_self_benchmark_yields_beta_one() -> None:
    asset, _, start, end = _padded_inputs()
    payload = _assemble(asset, asset["adj_close"], start, end, benchmark="TEST")
    assert payload.stats.beta == pytest.approx(1.0)
    assert payload.stats.correlation == pytest.approx(1.0)


# ---------------------------------------------------------------------------
# Candles
# ---------------------------------------------------------------------------


def test_daily_candles_are_in_range_raw_prices() -> None:
    asset, benchmark, start, end = _padded_inputs()
    payload = _assemble(asset, benchmark, start, end)
    # Every in-range trading day yields exactly one daily candle (252 visible
    # trading days; +1 when the calendar day at `start` is itself a trading day).
    expected = int((asset.index >= pd.Timestamp(start)).sum())
    assert len(payload.candles) == expected
    assert expected in (252, 253)
    assert payload.candles[0].date >= start
    assert payload.candles[-1].date == end
    # Raw close, not adjusted (they coincide here, but volume proves the row).
    assert payload.candles[0].volume == 1_000


def test_max_range_resamples_to_weekly_candles() -> None:
    asset, benchmark, _, end = _padded_inputs()
    start = asset.index[0].date()  # MAX: visible from the first available date
    payload = _assemble(asset, benchmark, start, end, range_key="MAX")

    # 400 business days ≈ 80 full weeks.
    assert 78 <= len(payload.candles) <= 82
    week = payload.candles[1]  # a full Mon-Fri week
    assert week.volume == 5_000  # summed daily volumes
    assert week.date.weekday() == 4  # W-FRI label
    assert week.low <= week.open <= week.high
    assert week.low <= week.close <= week.high


def test_candle_cap_exceeded_raises_payload_too_large() -> None:
    asset, benchmark, start, end = _padded_inputs()
    with pytest.raises(PayloadTooLargeError, match="exceeding the maximum"):
        _assemble(asset, benchmark, start, end, max_candles=10)


# ---------------------------------------------------------------------------
# Cumulative returns
# ---------------------------------------------------------------------------


def test_cumulative_series_start_at_zero_on_shared_grid() -> None:
    asset, benchmark, start, end = _padded_inputs()
    payload = _assemble(asset, benchmark, start, end)

    asset_pts = payload.cumulative_returns.asset
    bench_pts = payload.cumulative_returns.benchmark
    assert asset_pts[0][1] == 0.0
    assert bench_pts[0][1] == 0.0
    assert asset_pts[0][0] == bench_pts[0][0]
    assert asset_pts[0][0] > start
    # Identical date grids (aligned before slicing).
    assert [p[0] for p in asset_pts] == [p[0] for p in bench_pts]


def test_cumulative_final_value_compounds_from_rebase_date() -> None:
    asset, benchmark, start, end = _padded_inputs()
    payload = _assemble(asset, benchmark, start, end)
    pts = payload.cumulative_returns.asset
    first_date, last_date = pts[0][0], pts[-1][0]
    base = float(asset.loc[pd.Timestamp(first_date), "adj_close"])
    final = float(asset.loc[pd.Timestamp(last_date), "adj_close"])
    assert pts[-1][1] == pytest.approx(final / base - 1.0)


# ---------------------------------------------------------------------------
# Rolling series
# ---------------------------------------------------------------------------


def test_rolling_series_sliced_to_range_and_nan_free() -> None:
    asset, benchmark, start, end = _padded_inputs()
    payload = _assemble(asset, benchmark, start, end)

    for series in (
        payload.rolling_volatility,
        payload.rolling_beta,
        payload.rolling_correlation,
    ):
        assert len(series) > 0
        assert all(date > start for date, _ in series)
        assert all(np.isfinite(value) for _, value in series)
        # Pad warm-up worked: the series covers the visible range from its
        # first trading day (first point within days of `start`).
        assert (series[0][0] - start).days <= 7
        assert series[-1][0] == end

    # Rolling series cover (essentially) every visible trading day.
    assert len(payload.rolling_volatility) == 252


# ---------------------------------------------------------------------------
# Insufficient data — loud 422 path, never partial stats
# ---------------------------------------------------------------------------


def test_too_few_in_range_returns_raises() -> None:
    asset, benchmark, _, end = _padded_inputs()
    start = end - dt.timedelta(days=3)  # only a couple of in-range returns
    with pytest.raises(InsufficientDataError, match="in-range daily returns"):
        _assemble(asset, benchmark, start, end)


def test_window_exceeding_history_raises() -> None:
    dates = pd.bdate_range("2025-01-01", periods=40)
    asset = _price_frame(dates, _walk(40, seed=3))
    benchmark = pd.Series(_walk(40, seed=4), index=dates, name="adj_close")
    with pytest.raises(InsufficientDataError, match="exceeds the available padded history"):
        _assemble(asset, benchmark, dates[0].date(), dates[-1].date(), window=63)


def test_empty_asset_frame_raises() -> None:
    _, benchmark, start, end = _padded_inputs()
    empty = build_price_frame([])
    with pytest.raises(InsufficientDataError, match="price rows"):
        _assemble(empty, benchmark, start, end)


# ---------------------------------------------------------------------------
# Builders and pad helper
# ---------------------------------------------------------------------------


def test_build_helpers_sort_by_date() -> None:
    rows = [
        (dt.date(2025, 1, 3), 2.0, 2.1, 1.9, 2.0, 10, 2.0),
        (dt.date(2025, 1, 2), 1.0, 1.1, 0.9, 1.0, 10, 1.0),
    ]
    frame = build_price_frame(rows)
    assert list(frame["close"]) == [1.0, 2.0]
    series = build_adj_close_series([(dt.date(2025, 1, 3), 2.0), (dt.date(2025, 1, 2), 1.0)])
    assert list(series) == [1.0, 2.0]


def test_lookback_pad_covers_trading_days() -> None:
    # 63 trading days ≈ 89 calendar days; pad must exceed that with slack.
    assert lookback_pad_days(63) == 104
    assert lookback_pad_days(10) == 29
