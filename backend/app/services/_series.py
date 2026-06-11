"""Shared line-series helpers for analysis payload assembly (F2 + F3).

Extracted from ``app.services.stock_analysis`` so the portfolio service can
reuse the exact same point emission, weekly bounding and cumulative-return
rebasing — same semantics, one implementation.

Scale contract (project-wide): all fractional quantities are decimal
fractions (0.05 = 5%), never 0-100.
"""

import datetime as dt

import pandas as pd

from app.analytics import cumulative_return_series
from app.analytics._validation import to_date


def series_points(series: pd.Series) -> list[tuple[dt.date, float]]:
    """Convert a date-indexed float series to ``[(date, value), ...]`` points."""
    return [
        (to_date(label), float(value))
        for label, value in zip(series.index, series.to_numpy(dtype=float), strict=True)
    ]


def resample_weekly(series: pd.Series) -> pd.Series:
    """Resample a daily date-indexed float series to W-FRI taking last-of-week.

    Empty weeks (all NaN) are dropped. Used for MAX-range line series so the
    payload stays bounded and the x-axis aligns with the weekly candle grid.
    """
    return series.resample("W-FRI").last().dropna()


def rebased_cumulative(returns: pd.Series) -> list[tuple[dt.date, float]]:
    """Cumulative-return points rebased to 0.0 at the first date of *returns*.

    The first in-range date is the rebase point (its close is the base NAV),
    so the chart starts at exactly 0; growth compounds from the second return
    onward.
    """
    points: list[tuple[dt.date, float]] = [(to_date(returns.index[0]), 0.0)]
    if len(returns) > 1:
        points.extend(series_points(cumulative_return_series(returns.iloc[1:])))
    return points


def rebased_cumulative_weekly(returns: pd.Series) -> list[tuple[dt.date, float]]:
    """Weekly cumulative-return points for MAX range, rebased to 0.0.

    Builds the full daily cumulative series (first point = 0.0, rest compound),
    then resamples to W-FRI taking last-of-week so the x-axis aligns with the
    MAX candle grid. The first emitted point is the first in-range Friday.
    """
    # Build a daily cumulative series indexed from the first in-range date.
    daily_cum = pd.Series(
        [0.0] + list(cumulative_return_series(returns.iloc[1:]).to_numpy(dtype=float))
        if len(returns) > 1
        else [0.0],
        index=returns.index[: (len(returns))],
    )
    return series_points(resample_weekly(daily_cum))
