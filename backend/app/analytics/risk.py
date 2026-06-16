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


def downside_deviation(returns: pd.Series, mar: float = 0.0) -> float:
    """Downside deviation below a Minimum Acceptable Return (MAR).

    ``sqrt(mean(min(R - MAR, 0)^2))`` over the full sample (N denominator,
    not N-1) — only shortfalls below ``mar`` contribute; upside is treated as
    zero. ``mar`` and inputs/result are per-period decimal fractions
    (0.05 = 5%), never 0-100. Mirrors the eVestment MAR-based downside
    deviation (legacy return_statistics_service._compute_downside_deviation).

    Raises:
        ValueError: if fewer than 2 returns are supplied or the input contains
            NaN values.
    """
    if len(returns) < 2:
        raise ValueError(
            f"downside_deviation requires at least 2 returns, got {len(returns)}"
        )
    reject_nan(returns, "downside_deviation")
    shortfall = np.minimum(returns.to_numpy(dtype=float) - mar, 0.0)
    return float(np.sqrt(np.mean(shortfall**2)))


def semi_deviation(returns: pd.Series) -> float:
    """Semi-deviation: downside deviation using the sample mean as threshold.

    ``sqrt(mean(min(R - mean(R), 0)^2))`` over the full sample (N denominator).
    Only returns below the series mean contribute. Inputs/result are per-period
    decimal fractions (0.05 = 5%), never 0-100. Mirrors the eVestment
    semi-deviation (legacy return_statistics_service._compute_semi_deviation).

    Raises:
        ValueError: if fewer than 2 returns are supplied or the input contains
            NaN values.
    """
    if len(returns) < 2:
        raise ValueError(
            f"semi_deviation requires at least 2 returns, got {len(returns)}"
        )
    reject_nan(returns, "semi_deviation")
    values = returns.to_numpy(dtype=float)
    shortfall = np.minimum(values - values.mean(), 0.0)
    return float(np.sqrt(np.mean(shortfall**2)))


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


def information_ratio(
    portfolio_returns: pd.Series,
    benchmark_returns: pd.Series,
    periods_per_year: int = 252,
) -> float:
    """Annualized Information Ratio of active returns vs a benchmark.

    NaN/inf inputs are rejected up front (fail-loud), then the series are
    aligned (inner join). With
    ``active = portfolio - benchmark``, the tracking error is
    ``TE = std(active, ddof=1) * sqrt(periods_per_year)`` and
    ``IR = mean(active) * periods_per_year / TE`` — the active-return form used
    by the risk_metrics worker's regression_metrics. The risk-free rate does
    not appear (it cancels in the active return). Inputs are decimal fractions
    (0.05 = 5%), never 0-100; the result is unitless.

    Raises:
        ValueError: if either input contains NaN/inf values (rejected up front,
            matching the fail-loud contract used by sharpe_ratio/sortino_ratio
            rather than silently dropping NaN rows), fewer than 10 aligned points
            remain, or the tracking error is 0 (IR undefined when the portfolio
            tracks the benchmark exactly).
    """
    reject_nan(portfolio_returns, "information_ratio")
    reject_nan(benchmark_returns, "information_ratio")
    p, b = align_returns(portfolio_returns, benchmark_returns)
    if len(p) < _MIN_TAIL_POINTS:
        raise ValueError(
            f"information_ratio requires at least {_MIN_TAIL_POINTS} common points, got {len(p)}"
        )
    active = p.to_numpy(dtype=float) - b.to_numpy(dtype=float)
    te = float(np.std(active, ddof=1) * math.sqrt(periods_per_year))
    if te == 0:
        raise ValueError("information_ratio is undefined: zero tracking error")
    return float(np.mean(active) * periods_per_year / te)


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


# ---------------------------------------------------------------------------
# Parametric Gaussian VaR / CVaR (fail-loud) and EVT POT-GPD (degraded carrier)
# ---------------------------------------------------------------------------

# EVT thresholds (ported from worker risk_metrics.evt_tail lines 250/254/264 and
# legacy pot_gpd): >=100 finite returns, >=30 strictly-positive losses, >=20
# exceedances over the POT threshold (90th pct, retried at 85th).
_EVT_MIN_OBS = 100
_EVT_MIN_LOSSES = 30
_EVT_MIN_EXCEEDANCES = 20


def parametric_var(returns: pd.Series, confidence: float = 0.95) -> float:
    """Parametric (Normal) Value-at-Risk as a POSITIVE decimal-fraction loss.

    ``VaR = -(mu + z*sigma)`` with ``z = norm.ppf(1 - confidence) < 0`` and
    ``sigma`` the sample std (ddof=1). Ported from cvar_service.compute_cvar's
    parametric branch (lines 222-242), negated to the Light positive-loss
    convention.

    Raises:
        ValueError: confidence not in (0, 1), fewer than 10 returns, NaN/inf in
            the input, or a (near-)zero-variance series (VaR undefined).
    """
    from scipy.stats import norm

    if not 0 < confidence < 1:
        raise ValueError(f"confidence must be in (0, 1), got {confidence}")
    if len(returns) < _MIN_TAIL_POINTS:
        raise ValueError(
            f"parametric_var requires at least {_MIN_TAIL_POINTS} returns, got {len(returns)}"
        )
    reject_nan(returns, "parametric_var")
    values = returns.to_numpy(dtype=float)
    mu = float(np.mean(values))
    sigma = float(np.std(values, ddof=1))
    if sigma < 1e-12:
        raise ValueError("parametric_var is undefined: returns have zero variance")
    z = float(norm.ppf(1 - confidence))
    return -(mu + z * sigma)


def parametric_cvar(returns: pd.Series, confidence: float = 0.95) -> float:
    """Parametric (Normal) Conditional VaR as a POSITIVE decimal-fraction loss.

    ``CVaR = -mu + sigma * phi(z) / (1 - confidence)`` with ``z = norm.ppf(1 -
    confidence)`` and ``phi`` the standard-normal pdf. Ported from
    cvar_service.compute_cvar's parametric branch (lines 222-242, ``cvar = mu -
    sigma*phi_z/(1-conf)``), negated to positive-loss.

    Raises:
        ValueError: confidence not in (0, 1), fewer than 10 returns, NaN/inf in
            the input, or a (near-)zero-variance series (CVaR undefined).
    """
    from scipy.stats import norm

    if not 0 < confidence < 1:
        raise ValueError(f"confidence must be in (0, 1), got {confidence}")
    if len(returns) < _MIN_TAIL_POINTS:
        raise ValueError(
            f"parametric_cvar requires at least {_MIN_TAIL_POINTS} returns, got {len(returns)}"
        )
    reject_nan(returns, "parametric_cvar")
    values = returns.to_numpy(dtype=float)
    mu = float(np.mean(values))
    sigma = float(np.std(values, ddof=1))
    if sigma < 1e-12:
        raise ValueError("parametric_cvar is undefined: returns have zero variance")
    z = float(norm.ppf(1 - confidence))
    phi_z = float(norm.pdf(z))
    return -mu + sigma * phi_z / (1 - confidence)


@dataclass(frozen=True)
class EvtTailResult:
    """EVT POT-GPD tail estimate with an explicit fail-CLOSED degraded carrier.

    Light analytics are normally fail-loud, but an EVT fit can legitimately be
    non-estimable (too few losses/exceedances, GPD MLE non-convergence, an
    infinite-mean tail). For those *data* conditions this carrier reports
    ``degraded=True`` with ``var``/``cvar`` = NaN and a ``degraded_reason`` —
    NEVER a silent 0.0 (a 0.0 would masquerade as "0% tail risk"). This mirrors
    the legacy cvar_service.CVaRResult carrier (lines 125-139, 185-186). A
    NaN/inf *input* is a caller bug and still raises ``ValueError`` up front.

    ``var``/``cvar`` are POSITIVE decimal-fraction loss magnitudes when not
    degraded; CVaR >= VaR by construction (xi < 1).
    """

    var: float
    cvar: float
    confidence: float
    degraded: bool
    degraded_reason: str | None
    evt_xi: float  # GPD shape (NaN when degraded)
    evt_beta: float  # GPD scale (NaN when degraded)
    evt_threshold: float  # POT threshold u in loss space (NaN when degraded)
    evt_n_exceedances: int  # exceedances over u (0 when degraded)


def _degraded_evt(confidence: float, reason: str) -> EvtTailResult:
    return EvtTailResult(
        var=float("nan"),
        cvar=float("nan"),
        confidence=confidence,
        degraded=True,
        degraded_reason=reason,
        evt_xi=float("nan"),
        evt_beta=float("nan"),
        evt_threshold=float("nan"),
        evt_n_exceedances=0,
    )


def evt_tail_var_cvar(returns: pd.Series, confidence: float = 0.99) -> EvtTailResult:
    """On-demand EVT POT-GPD VaR/CVaR for the deep loss tail (fail-closed carrier).

    Ports the offline-proven recipe from the workers repo
    (``src/workers/risk_metrics.py::evt_tail``, lines 243-293): work in loss
    space (``losses = -returns``, keep the strictly-positive losses), pick a
    peaks-over-threshold cut at the 90th loss percentile (retry at the 85th if
    too few exceedances), fit a GPD to the exceedances via
    ``scipy.stats.genpareto.fit(exceed, floc=0)``, then apply the McNeil-Frey
    closed-form tail quantile and expected-shortfall:

        ratio = (n / n_u) * (1 - confidence)
        VaR   = u + (beta/xi) * (ratio**(-xi) - 1)            (xi != 0)
              = u - beta * log(ratio)                          (xi ~ 0)
        CVaR  = VaR/(1 - xi) + (beta - xi*u)/(1 - xi)          (xi < 1)

    Returns POSITIVE loss magnitudes (the worker negates at the end for its
    return-space table; here we keep them positive). The ``max(var_loss, u)``
    clamp is from legacy pot_gpd.py line 205 (POT VaR is bounded below by the
    threshold); harmless for the deep tail. Degrades fail-closed (NaN + reason)
    on: fewer than 100 finite returns, fewer than 30 positive losses, fewer than
    20 exceedances at either threshold, GPD MLE failure / non-positive scale, or
    an infinite-mean tail (xi >= 1, ES undefined).

    Raises:
        ValueError: confidence not in (0, 1), or NaN/inf in the input.
    """
    from scipy.stats import genpareto

    if not 0 < confidence < 1:
        raise ValueError(f"confidence must be in (0, 1), got {confidence}")
    reject_nan(returns, "evt_tail_var_cvar")
    values = returns.to_numpy(dtype=float)
    if values.size < _EVT_MIN_OBS:
        return _degraded_evt(confidence, "insufficient_obs")

    losses = -values
    losses = losses[losses > 0]
    if losses.size < _EVT_MIN_LOSSES:
        return _degraded_evt(confidence, "insufficient_losses")

    # POT threshold at the 90th loss percentile; drop to 85th if too few exceed.
    exceed = np.array([])
    u = float("nan")
    for q in (0.90, 0.85):
        u = float(np.quantile(losses, q))
        exceed = losses[losses > u] - u
        if exceed.size >= _EVT_MIN_EXCEEDANCES:
            break
    else:
        return _degraded_evt(confidence, "insufficient_exceedances")

    n = int(losses.size)
    n_u = int(exceed.size)
    try:
        xi, _loc, beta = genpareto.fit(exceed, floc=0.0)
    except Exception:
        return _degraded_evt(confidence, "gpd_fit_failed")
    xi = float(xi)
    beta = float(beta)
    if beta <= 0 or not np.isfinite(xi):
        return _degraded_evt(confidence, "gpd_fit_invalid")
    if xi >= 1.0:
        # Infinite-mean tail — expected shortfall undefined.
        return _degraded_evt(confidence, "infinite_mean_tail")

    # McNeil-Frey closed form (worker recipe lines 277-286).
    ratio = (n / n_u) * (1.0 - confidence)
    if abs(xi) > 1e-8:
        var_loss = u + (beta / xi) * (ratio ** (-xi) - 1.0)
    else:
        var_loss = u - beta * math.log(ratio)
    var_loss = max(var_loss, u)  # POT VaR bounded below by threshold (pot_gpd L205)
    cvar_loss = var_loss / (1.0 - xi) + (beta - xi * u) / (1.0 - xi)

    if not (np.isfinite(var_loss) and np.isfinite(cvar_loss)):
        return _degraded_evt(confidence, "non_finite_estimate")

    return EvtTailResult(
        var=float(var_loss),
        cvar=float(cvar_loss),
        confidence=confidence,
        degraded=False,
        degraded_reason=None,
        evt_xi=xi,
        evt_beta=beta,
        evt_threshold=u,
        evt_n_exceedances=n_u,
    )
