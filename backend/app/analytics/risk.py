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

from app.analytics._validation import reject_nan, to_date
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
class DrawdownEpisode:
    """One drawdown episode of a price/NAV series.

    ``depth`` is a NEGATIVE decimal fraction (e.g. -0.20 = a 20% peak-to-trough
    loss), never 0-100. ``peak_date`` is the running-max date at the ONSET of
    the drawdown; ``trough_date`` is the deepest point; ``recovery_date`` is the
    first date the series regains its prior peak (``None`` for an OPEN,
    unrecovered episode). Durations are CALENDAR days: ``duration_days`` spans
    peak -> recovery (peak -> last date for an open episode) and
    ``recovery_days`` spans trough -> recovery (``None`` while open).
    """

    depth: float
    peak_date: date
    trough_date: date
    recovery_date: date | None
    duration_days: int
    recovery_days: int | None


@dataclass(frozen=True)
class BestWorst:
    """Best and worst single-period returns (decimal fractions) and their dates."""

    best_return: float
    best_date: date
    worst_return: float
    worst_date: date


def annualized_volatility(returns: pd.Series, periods_per_year: int = 252) -> float:
    """Annualized volatility of a return series.

    Sample standard deviation (ddof=1) scaled by ``sqrt(periods_per_year)``.
    Input returns and the result are decimal fractions (0.05 = 5%), never 0-100.

    Raises:
        ValueError: if fewer than 2 returns are supplied or the input contains
            NaN values.
    """
    if len(returns) < 2:
        raise ValueError(
            f"annualized_volatility requires at least 2 returns, got {len(returns)}"
        )
    reject_nan(returns, "annualized_volatility")
    vol = float(returns.std(ddof=1, skipna=False)) * math.sqrt(periods_per_year)
    return vol


def historical_var(returns: pd.Series, confidence: float = 0.95) -> float:
    """Historical Value-at-Risk as a POSITIVE decimal fraction.

    Computed as ``-quantile(returns, 1 - confidence)`` using numpy's default
    linear interpolation (``method='linear'``, type-7), i.e. interpolation at
    position ``(n-1) * p`` in the sorted array. Sign convention: VaR 95 = 0.02
    means "5% of days lose more than 2%". Inputs and result are decimal
    fractions (0.05 = 5%), never 0-100.

    Raises:
        ValueError: if ``confidence`` is not in (0, 1), fewer than 10 returns
            are supplied, or the input contains NaN values.
    """
    if not 0 < confidence < 1:
        raise ValueError(f"confidence must be in (0, 1), got {confidence}")
    if len(returns) < _MIN_TAIL_POINTS:
        raise ValueError(
            f"historical_var requires at least {_MIN_TAIL_POINTS} returns, got {len(returns)}"
        )
    reject_nan(returns, "historical_var")
    var = -float(np.quantile(returns.to_numpy(dtype=float), 1 - confidence))
    return var


def historical_cvar(returns: pd.Series, confidence: float = 0.95) -> float:
    """Historical Conditional VaR (expected shortfall) as a POSITIVE decimal fraction.

    Computed as ``-mean(returns[returns <= quantile(returns, 1 - confidence)])``.
    Same sign convention as :func:`historical_var`: CVaR 95 = 0.03 means "on
    the worst 5% of days, the average loss is 3%". Inputs and result are
    decimal fractions (0.05 = 5%), never 0-100.

    Raises:
        ValueError: if ``confidence`` is not in (0, 1), fewer than 10 returns
            are supplied, the tail selection is empty, or the input contains
            NaN values.
    """
    if not 0 < confidence < 1:
        raise ValueError(f"confidence must be in (0, 1), got {confidence}")
    if len(returns) < _MIN_TAIL_POINTS:
        raise ValueError(
            f"historical_cvar requires at least {_MIN_TAIL_POINTS} returns, got {len(returns)}"
        )
    reject_nan(returns, "historical_cvar")
    values = returns.to_numpy(dtype=float)
    cutoff = float(np.quantile(values, 1 - confidence))
    tail = values[values <= cutoff]
    if tail.size == 0:
        raise ValueError("historical_cvar tail selection is empty")
    cvar = -float(tail.mean())
    return cvar


def max_drawdown(prices: pd.Series) -> DrawdownResult:
    """Maximum drawdown of a price/NAV series via running maximum.

    ``depth`` is a NEGATIVE decimal fraction (e.g. -0.35 = 35% peak-to-trough
    loss), never 0-100. ``peak_date`` is the date of the running maximum
    preceding the trough; ``trough_date`` is the date of the deepest point.
    For a monotonically rising series the depth is 0.0 and peak and trough
    coincide.

    Raises:
        ValueError: if fewer than 2 prices are supplied or the input contains
            NaN values.
    """
    if len(prices) < 2:
        raise ValueError(f"max_drawdown requires at least 2 prices, got {len(prices)}")
    reject_nan(prices, "max_drawdown")
    running_max = prices.cummax()
    drawdowns = prices / running_max - 1
    trough_label = drawdowns.idxmin()
    depth = float(drawdowns.loc[trough_label])
    peak_label = prices.loc[:trough_label].idxmax()
    return DrawdownResult(
        depth=depth,
        peak_date=to_date(peak_label),
        trough_date=to_date(trough_label),
    )


def drawdown_episodes(prices: pd.Series, top_n: int = 5) -> list["DrawdownEpisode"]:
    """Top-``top_n`` worst drawdown episodes of a price/NAV series, deepest first.

    An episode runs from the most recent peak (drawdown == 0) preceding a loss,
    through the deepest trough, to the first date the series regains that peak.
    The final episode is OPEN (``recovery_date=None``) when the series never
    recovers by the last date. ``depth`` values are NEGATIVE decimal fractions
    (never 0-100); durations are calendar days. For a monotonically rising
    series the result is an empty list.

    Ported from the legacy ``extract_drawdown_periods``: the onset peak is
    captured in a SEPARATE index (``peak_idx``) at drawdown onset, distinct
    from the rolling ``last_peak_idx`` cursor, because the recovery bar itself
    has ``drawdown == 0`` and would otherwise overwrite the cursor.

    Raises:
        ValueError: if ``top_n`` < 1, fewer than 2 prices are supplied, or the
            input contains NaN/infinite values.
    """
    if top_n < 1:
        raise ValueError(f"top_n must be >= 1, got {top_n}")
    if len(prices) < 2:
        raise ValueError(
            f"drawdown_episodes requires at least 2 prices, got {len(prices)}"
        )
    reject_nan(prices, "drawdown_episodes")

    values = prices.to_numpy(dtype=float)
    running_max = np.maximum.accumulate(values)
    dd = values / running_max - 1.0  # <= 0; 0 at every new running high

    labels = list(prices.index)
    episodes: list[DrawdownEpisode] = []
    in_dd = False
    last_peak_idx = 0
    peak_idx = 0
    trough_idx = 0
    trough_val = 0.0

    for i, d in enumerate(dd):
        if d == 0:
            last_peak_idx = i

        if d < 0:
            if not in_dd:
                in_dd = True
                peak_idx = last_peak_idx  # onset peak — captured ONCE per episode
                trough_idx = i
                trough_val = d
            elif d < trough_val:
                trough_idx = i
                trough_val = d
        elif in_dd:
            # Recovery: d == 0 means a new running high was reached at index i.
            episodes.append(
                DrawdownEpisode(
                    depth=float(trough_val),
                    peak_date=to_date(labels[peak_idx]),
                    trough_date=to_date(labels[trough_idx]),
                    recovery_date=to_date(labels[i]),
                    duration_days=(
                        to_date(labels[i]) - to_date(labels[peak_idx])
                    ).days,
                    recovery_days=(
                        to_date(labels[i]) - to_date(labels[trough_idx])
                    ).days,
                )
            )
            in_dd = False

    if in_dd:
        episodes.append(
            DrawdownEpisode(
                depth=float(trough_val),
                peak_date=to_date(labels[peak_idx]),
                trough_date=to_date(labels[trough_idx]),
                recovery_date=None,
                duration_days=(
                    to_date(labels[-1]) - to_date(labels[peak_idx])
                ).days,
                recovery_days=None,
            )
        )

    episodes.sort(key=lambda e: e.depth)
    return episodes[:top_n]


def best_worst_day(returns: pd.Series) -> BestWorst:
    """Best and worst single-period returns with their dates.

    Returns are decimal fractions (0.05 = 5%), never 0-100. ``idxmax`` and
    ``idxmin`` skip NaN by default, so the guard is applied up-front to ensure
    the returned dates and values are not influenced by NaN entries.

    Raises:
        ValueError: if ``returns`` is empty or contains NaN values.
    """
    if len(returns) < 1:
        raise ValueError("best_worst_day requires at least 1 return, got 0")
    reject_nan(returns, "best_worst_day")
    best_label = returns.idxmax()
    worst_label = returns.idxmin()
    best = float(returns.loc[best_label])
    worst = float(returns.loc[worst_label])
    return BestWorst(
        best_return=best,
        best_date=to_date(best_label),
        worst_return=worst,
        worst_date=to_date(worst_label),
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
