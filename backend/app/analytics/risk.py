"""Single-asset risk statistics.

Scale contract (project-wide): all fractional quantities (returns, vol,
VaR, CVaR, drawdown) are decimal fractions (0.05 = 5%), never 0-100.

All scalar functions fail loud with ``ValueError`` on insufficient data and
never return NaN.
"""

import math
from dataclasses import dataclass
from datetime import date

import numpy as np
import pandas as pd

from app.analytics.returns import align_returns

_MIN_TAIL_POINTS = 10


@dataclass(frozen=True)
class DrawdownResult:
    """Maximum drawdown of a price/NAV series.

    ``depth`` is a NEGATIVE decimal fraction (e.g. -0.35 = a 35% drawdown).
    """

    depth: float
    peak_date: date
    trough_date: date


@dataclass(frozen=True)
class BestWorst:
    """Best and worst single-period returns (decimal fractions) and their dates."""

    best_return: float
    best_date: date
    worst_return: float
    worst_date: date


def _to_date(value: object) -> date:
    """Coerce an index label (Timestamp, datetime or date) to a ``date``."""
    if isinstance(value, pd.Timestamp):
        return value.date()
    if isinstance(value, date):
        return value
    return pd.Timestamp(value).date()  # type: ignore[arg-type]


def annualized_volatility(returns: pd.Series, periods_per_year: int = 252) -> float:
    """Annualized volatility of a return series.

    Sample standard deviation (ddof=1) scaled by ``sqrt(periods_per_year)``.
    Input returns and the result are decimal fractions (0.05 = 5%), never 0-100.

    Raises:
        ValueError: if fewer than 2 returns are supplied or the result is NaN.
    """
    if len(returns) < 2:
        raise ValueError(
            f"annualized_volatility requires at least 2 returns, got {len(returns)}"
        )
    vol = float(returns.std(ddof=1, skipna=False)) * math.sqrt(periods_per_year)
    if math.isnan(vol):
        raise ValueError("annualized_volatility is NaN; input contains NaN values")
    return vol


def historical_var(returns: pd.Series, confidence: float = 0.95) -> float:
    """Historical Value-at-Risk as a POSITIVE decimal fraction.

    Computed as ``-quantile(returns, 1 - confidence)`` with numpy's default
    linear interpolation. Sign convention: VaR 95 = 0.02 means "5% of days
    lose more than 2%". Inputs and result are decimal fractions (0.05 = 5%),
    never 0-100.

    Raises:
        ValueError: if ``confidence`` is not in (0, 1), fewer than 10 returns
            are supplied, or the result is NaN.
    """
    if not 0 < confidence < 1:
        raise ValueError(f"confidence must be in (0, 1), got {confidence}")
    if len(returns) < _MIN_TAIL_POINTS:
        raise ValueError(
            f"historical_var requires at least {_MIN_TAIL_POINTS} returns, got {len(returns)}"
        )
    var = -float(np.quantile(returns.to_numpy(dtype=float), 1 - confidence))
    if math.isnan(var):
        raise ValueError("historical_var is NaN; input contains NaN values")
    return var


def historical_cvar(returns: pd.Series, confidence: float = 0.95) -> float:
    """Historical Conditional VaR (expected shortfall) as a POSITIVE decimal fraction.

    Computed as ``-mean(returns[returns <= quantile(returns, 1 - confidence)])``.
    Same sign convention as :func:`historical_var`: CVaR 95 = 0.03 means "on
    the worst 5% of days, the average loss is 3%". Inputs and result are
    decimal fractions (0.05 = 5%), never 0-100.

    Raises:
        ValueError: if ``confidence`` is not in (0, 1), fewer than 10 returns
            are supplied, the tail selection is empty, or the result is NaN.
    """
    if not 0 < confidence < 1:
        raise ValueError(f"confidence must be in (0, 1), got {confidence}")
    if len(returns) < _MIN_TAIL_POINTS:
        raise ValueError(
            f"historical_cvar requires at least {_MIN_TAIL_POINTS} returns, got {len(returns)}"
        )
    values = returns.to_numpy(dtype=float)
    cutoff = float(np.quantile(values, 1 - confidence))
    tail = values[values <= cutoff]
    if tail.size == 0:
        raise ValueError("historical_cvar tail selection is empty")
    cvar = -float(tail.mean())
    if math.isnan(cvar):
        raise ValueError("historical_cvar is NaN; input contains NaN values")
    return cvar


def max_drawdown(prices: pd.Series) -> DrawdownResult:
    """Maximum drawdown of a price/NAV series via running maximum.

    ``depth`` is a NEGATIVE decimal fraction (e.g. -0.35 = 35% peak-to-trough
    loss), never 0-100. ``peak_date`` is the date of the running maximum
    preceding the trough; ``trough_date`` is the date of the deepest point.
    For a monotonically rising series the depth is 0.0 and peak and trough
    coincide.

    Raises:
        ValueError: if fewer than 2 prices are supplied or the result is NaN.
    """
    if len(prices) < 2:
        raise ValueError(f"max_drawdown requires at least 2 prices, got {len(prices)}")
    running_max = prices.cummax()
    drawdowns = prices / running_max - 1
    trough_label = drawdowns.idxmin()
    depth = float(drawdowns.loc[trough_label])
    if math.isnan(depth):
        raise ValueError("max_drawdown is NaN; input contains NaN values")
    peak_label = prices.loc[:trough_label].idxmax()
    return DrawdownResult(
        depth=depth,
        peak_date=_to_date(peak_label),
        trough_date=_to_date(trough_label),
    )


def best_worst_day(returns: pd.Series) -> BestWorst:
    """Best and worst single-period returns with their dates.

    Returns are decimal fractions (0.05 = 5%), never 0-100.

    Raises:
        ValueError: if ``returns`` is empty or contains NaN extremes.
    """
    if len(returns) < 1:
        raise ValueError("best_worst_day requires at least 1 return, got 0")
    best_label = returns.idxmax()
    worst_label = returns.idxmin()
    best = float(returns.loc[best_label])
    worst = float(returns.loc[worst_label])
    if math.isnan(best) or math.isnan(worst):
        raise ValueError("best_worst_day is NaN; input contains NaN values")
    return BestWorst(
        best_return=best,
        best_date=_to_date(best_label),
        worst_return=worst,
        worst_date=_to_date(worst_label),
    )


def beta(asset_returns: pd.Series, benchmark_returns: pd.Series) -> float:
    """Beta of an asset versus a benchmark.

    Series are aligned first (inner join, NaNs dropped); then
    ``cov(a, b, ddof=1) / var(b, ddof=1)``. Inputs are decimal fractions
    (0.05 = 5%), never 0-100.

    Raises:
        ValueError: if fewer than 10 common points or the benchmark variance
            is 0 (beta undefined).
    """
    a, b = align_returns(asset_returns, benchmark_returns)
    if len(a) < _MIN_TAIL_POINTS:
        raise ValueError(
            f"beta requires at least {_MIN_TAIL_POINTS} common points, got {len(a)}"
        )
    bench_var = float(b.var(ddof=1))
    if bench_var == 0:
        raise ValueError("beta is undefined: benchmark variance is 0")
    cov = float(np.cov(a.to_numpy(dtype=float), b.to_numpy(dtype=float), ddof=1)[0, 1])
    return cov / bench_var


def correlation(asset_returns: pd.Series, benchmark_returns: pd.Series) -> float:
    """Pearson correlation of an asset versus a benchmark.

    Series are aligned first (inner join, NaNs dropped). Inputs are decimal
    fractions (0.05 = 5%), never 0-100.

    Raises:
        ValueError: if fewer than 10 common points or either series has zero
            variance (correlation undefined).
    """
    a, b = align_returns(asset_returns, benchmark_returns)
    if len(a) < _MIN_TAIL_POINTS:
        raise ValueError(
            f"correlation requires at least {_MIN_TAIL_POINTS} common points, got {len(a)}"
        )
    if float(b.var(ddof=1)) == 0 or float(a.var(ddof=1)) == 0:
        raise ValueError("correlation is undefined: a series has zero variance")
    corr = float(a.corr(b))
    if math.isnan(corr):
        raise ValueError("correlation is NaN; input contains NaN values")
    return corr
