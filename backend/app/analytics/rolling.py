"""Rolling-window statistics.

Scale contract (project-wide): all fractional quantities are decimal
fractions (0.05 = 5%), never 0-100.

All functions return a ``pd.Series`` indexed like the (aligned) input with
``min_periods=window``: the first ``window - 1`` values are NaN by
construction. A NaN inside the series means the window is undefined at that
point (e.g. zero benchmark variance); an upstream filter is expected to drop
NaNs before serving the data.
"""

import math

import numpy as np
import pandas as pd

from app.analytics.returns import align_returns


def _validate_window(window: int, aligned_length: int, name: str) -> None:
    if window < 2:
        raise ValueError(f"{name} requires window >= 2, got {window}")
    if aligned_length < window:
        raise ValueError(
            f"{name} requires at least window={window} points, got {aligned_length}"
        )


def rolling_volatility(
    returns: pd.Series, window: int = 63, periods_per_year: int = 252
) -> pd.Series:
    """Rolling annualized volatility (decimal fraction, 0.05 = 5%).

    Rolling sample std (ddof=1, ``min_periods=window``) scaled by
    ``sqrt(periods_per_year)``. The first ``window - 1`` values are NaN by
    construction.

    Raises:
        ValueError: if ``window < 2`` or ``len(returns) < window``.
    """
    _validate_window(window, len(returns), "rolling_volatility")
    return returns.rolling(window, min_periods=window).std(ddof=1) * math.sqrt(
        periods_per_year
    )


def rolling_beta(
    asset_returns: pd.Series, benchmark_returns: pd.Series, window: int = 63
) -> pd.Series:
    """Rolling beta of an asset versus a benchmark.

    Series are aligned first (inner join, NaNs dropped); the result is indexed
    by the aligned index. Computed as rolling sample covariance divided by
    rolling sample variance of the benchmark (both ddof=1,
    ``min_periods=window``), with no Python-level loop. The first
    ``window - 1`` values are NaN by construction; windows with zero benchmark
    variance yield NaN (undefined window — an upstream filter drops them).
    Inputs are decimal fractions (0.05 = 5%), never 0-100.

    Raises:
        ValueError: if ``window < 2`` or fewer than ``window`` aligned points.
    """
    a, b = align_returns(asset_returns, benchmark_returns)
    _validate_window(window, len(a), "rolling_beta")
    cov = a.rolling(window, min_periods=window).cov(b)
    var = b.rolling(window, min_periods=window).var(ddof=1)
    return cov / var.replace(0.0, np.nan)


def rolling_correlation(
    asset_returns: pd.Series, benchmark_returns: pd.Series, window: int = 63
) -> pd.Series:
    """Rolling Pearson correlation of an asset versus a benchmark.

    Series are aligned first (inner join, NaNs dropped); the result is indexed
    by the aligned index. The first ``window - 1`` values are NaN by
    construction; windows where either side has zero variance yield NaN
    (undefined window — an upstream filter drops them). Inputs are decimal
    fractions (0.05 = 5%), never 0-100.

    Raises:
        ValueError: if ``window < 2`` or fewer than ``window`` aligned points.
    """
    a, b = align_returns(asset_returns, benchmark_returns)
    _validate_window(window, len(a), "rolling_correlation")
    return a.rolling(window, min_periods=window).corr(b)


def rolling_annualized_return(
    returns: pd.Series, window: int = 63, periods_per_year: int = 252
) -> pd.Series:
    """Rolling annualized total return (decimal fraction, 0.05 = 5%).

    For each trailing window of ``window`` daily returns, compounds them
    (``prod(1 + r)``) and annualizes by raising to ``periods_per_year / window``
    minus 1 — the legacy fact-sheet convention
    (``quant_engine/rolling_service.py`` line 78). Uses ``min_periods=window``
    so the first ``window - 1`` values are NaN by construction; an upstream
    filter is expected to drop the leading NaNs before serving. Inputs and
    result are decimal fractions (0.05 = 5%), never 0-100.

    Standard institutional windows (caller-chosen): 21 (1M), 63 (3M),
    126 (6M), 252 (1Y).

    Raises:
        ValueError: if ``window < 2`` or ``len(returns) < window``.
    """
    _validate_window(window, len(returns), "rolling_annualized_return")
    growth = (1.0 + returns).rolling(window, min_periods=window).apply(
        np.prod, raw=True
    )
    return growth ** (periods_per_year / window) - 1.0
