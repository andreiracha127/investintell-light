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

# Canonical annual risk-free rate (matches the worker risk_metrics rf handling
# and the legacy return_statistics_service.DEFAULT_RISK_FREE_RATE = 0.04). Used
# when a request carries no explicit rate.
DEFAULT_RISK_FREE_RATE = 0.04

# Risk-adjusted ratios need a meaningful sample; reuse the tail-points floor.
_MIN_RATIO_POINTS = _MIN_TAIL_POINTS


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


def sharpe_ratio(
    returns: pd.Series,
    risk_free_rate: float = DEFAULT_RISK_FREE_RATE,
    periods_per_year: int = 252,
) -> float:
    """Annualized Sharpe ratio of a daily return series.

    ``excess = returns - risk_free_rate / periods_per_year``; the ratio is
    ``mean(excess) / std(excess, ddof=1) * sqrt(periods_per_year)`` — the
    canonical arithmetic-mean daily-excess form used by the risk_metrics
    worker and the legacy return_statistics_service. Inputs and ``risk_free_rate``
    are decimal fractions (0.04 = 4%), never 0-100; the result is unitless.

    Raises:
        ValueError: if fewer than 10 returns are supplied, the input contains
            NaN/inf values, or the excess-return volatility is 0 (Sharpe
            undefined for a constant series).
    """
    if len(returns) < _MIN_RATIO_POINTS:
        raise ValueError(
            f"sharpe_ratio requires at least {_MIN_RATIO_POINTS} returns, got {len(returns)}"
        )
    reject_nan(returns, "sharpe_ratio")
    excess = returns.to_numpy(dtype=float) - risk_free_rate / periods_per_year
    if float(np.ptp(excess)) == 0:
        raise ValueError("sharpe_ratio is undefined: zero volatility (constant series)")
    vol = float(np.std(excess, ddof=1))
    return float(np.mean(excess) / vol * math.sqrt(periods_per_year))


def sortino_ratio(
    returns: pd.Series,
    risk_free_rate: float = DEFAULT_RISK_FREE_RATE,
    periods_per_year: int = 252,
) -> float:
    """Annualized Sortino ratio with canonical Target Downside Deviation.

    ``excess = returns - risk_free_rate / periods_per_year``; the denominator is
    the Target Downside Deviation ``TDD = sqrt(mean(min(excess, 0)**2))`` over
    the FULL sample (N denominator, matching the risk_metrics worker and the
    legacy return_statistics_service). The ratio is
    ``mean(excess) / TDD * sqrt(periods_per_year)``. Inputs are decimal
    fractions (0.04 = 4%), never 0-100; the result is unitless.

    Raises:
        ValueError: if fewer than 10 returns are supplied, the input contains
            NaN/inf values, or there is no downside (TDD == 0), which leaves the
            ratio undefined.
    """
    if len(returns) < _MIN_RATIO_POINTS:
        raise ValueError(
            f"sortino_ratio requires at least {_MIN_RATIO_POINTS} returns, got {len(returns)}"
        )
    reject_nan(returns, "sortino_ratio")
    excess = returns.to_numpy(dtype=float) - risk_free_rate / periods_per_year
    shortfall = np.minimum(excess, 0.0)
    tdd = float(np.sqrt(np.mean(shortfall**2)))
    if tdd == 0:
        raise ValueError(
            "sortino_ratio is undefined: no downside (target downside deviation is 0)"
        )
    return float(np.mean(excess) / tdd * math.sqrt(periods_per_year))


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


def realized_cvar(returns: pd.Series, confidence: float = 0.95) -> float:
    """Exact Rockafellar–Uryasev empirical CVaR as a POSITIVE decimal fraction.

    This is the estimator the min-CVaR optimizer minimizes
    (``app.optimizer.engine.solve_min_cvar``): with single-asset losses
    ``L = -returns`` and ``alpha = confidence``,

        VaR_a  = upper alpha-quantile of L (``np.quantile(L, alpha, method="higher")``)
        CVaR_a = VaR_a + (1/((1-alpha)*T)) * sum(max(L_t - VaR_a, 0))

    At optimality this equals ``min_z [ z + sum(max(L - z, 0))/((1-alpha)*T) ]``,
    i.e. the optimizer's objective value, so the builder's in-sample report is
    consistent with the objective the weights were chosen to minimize. Unlike
    :func:`historical_cvar` (a naive tail-mean), this is exact even when the
    expected tail size ``(1-alpha)*T`` is non-integer.

    Same sign convention as :func:`historical_cvar`: a result of 0.03 means "on
    the worst ~5% of days the conditional expected loss is 3%". Inputs and
    result are decimal fractions (0.05 = 5%), never 0-100.

    Raises:
        ValueError: if ``confidence`` is not in (0, 1), fewer than 10 returns
            are supplied, or the input contains NaN/infinite values.
    """
    if not 0 < confidence < 1:
        raise ValueError(f"confidence must be in (0, 1), got {confidence}")
    if len(returns) < _MIN_TAIL_POINTS:
        raise ValueError(
            f"realized_cvar requires at least {_MIN_TAIL_POINTS} returns, got {len(returns)}"
        )
    reject_nan(returns, "realized_cvar")
    losses = -returns.to_numpy(dtype=float)
    t = losses.size
    var_loss = float(np.quantile(losses, confidence, method="higher"))
    excess = np.maximum(losses - var_loss, 0.0)
    cvar = var_loss + float(excess.sum()) / ((1.0 - confidence) * t)
    return float(cvar)


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
