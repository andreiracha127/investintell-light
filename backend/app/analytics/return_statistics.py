"""eVestment risk/return ratios for the fact-sheet pack.

Ports the absolute-return and risk-adjusted half of
quant_engine/return_statistics_service.compute_return_statistics into the light
analytics idiom: each ratio is a fail-loud pure function over a daily-return
pd.Series (decimal fractions), aggregated to monthly via to_monthly_returns.

Conventions (pinned to legacy parity):
- monthly returns: fixed 21-day end-anchored blocks (see to_monthly_returns);
- geometric annualization: (1 + monthly_geo_mean)**12 - 1 (legacy _annualize_monthly);
- Sterling denominator: |avg_yearly_max_dd - 0.10| (Kestner additive cushion);
- Omega: sum(max(r-MAR,0)) / sum(|min(r-MAR,0)|) on monthly returns;
- Treynor: (ann_geo_return - rf) / beta_monthly;
- Jensen: 12 * (mean(r) - rf/12 - beta*(mean(bm) - rf/12)).

Scale contract: returns are decimal fractions (0.05 = 5%). rf is an ANNUAL rate.
Gate G5: none of these consume a sample mean as an optimizer expected-return
input; they are descriptive fact-sheet statistics.
"""

from dataclasses import dataclass

import numpy as np
import pandas as pd

from app.analytics.returns import align_returns, to_monthly_returns
from app.analytics.risk import beta, max_drawdown

_MIN_DAYS_ONE_YEAR = 252
_MIN_MONTHS_REGRESSION = 12
DEFAULT_RISK_FREE_RATE = 0.04
_MONTHS_PER_YEAR = 12


def geometric_mean_monthly(daily_returns: pd.Series) -> float:
    """Geometric mean of the monthly return series (decimal fraction).

    ``prod(1 + monthly)**(1/n) - 1`` over the 21-day end-anchored months.

    Raises:
        ValueError: if fewer than 21 daily returns (no full month) or the
            input contains NaN values.
    """
    monthly = to_monthly_returns(daily_returns)
    return float(np.prod(1.0 + monthly.to_numpy(dtype=float)) ** (1.0 / len(monthly)) - 1.0)


def omega_ratio(daily_returns: pd.Series, mar: float = 0.0) -> float:
    """Omega ratio at a monthly minimum-acceptable-return threshold.

    ``sum(max(r - MAR, 0)) / sum(|min(r - MAR, 0)|)`` over monthly returns.

    Raises:
        ValueError: if fewer than 21 daily returns, NaN input, or there is no
            downside below MAR (denominator zero — Omega undefined).
    """
    monthly = to_monthly_returns(daily_returns).to_numpy(dtype=float)
    gains = float(np.sum(np.maximum(monthly - mar, 0.0)))
    losses = float(np.sum(np.abs(np.minimum(monthly - mar, 0.0))))
    if losses < 1e-12:
        raise ValueError("omega_ratio is undefined: no downside below MAR")
    return gains / losses


def sterling_ratio(daily_returns: pd.Series) -> float:
    """Sterling ratio = ann_geo_return / |avg_yearly_max_dd - 0.10|.

    Splits the daily series into 252-day yearly chunks anchored to the END,
    averages each chunk's max drawdown (via :func:`max_drawdown` on the chunk
    NAV), and applies the Kestner additive 10% cushion to the denominator.
    ``avg_max_dd`` is negative, so the subtraction increases the denominator.

    Raises:
        ValueError: if fewer than 252 daily returns, NaN/infinite input, or the
            denominator collapses to <= 0.
    """
    if len(daily_returns) < _MIN_DAYS_ONE_YEAR:
        raise ValueError(
            f"sterling_ratio requires at least {_MIN_DAYS_ONE_YEAR} daily "
            f"returns, got {len(daily_returns)}"
        )
    arr = daily_returns.to_numpy(dtype=float)
    if not np.isfinite(arr).all():
        raise ValueError("sterling_ratio received NaN or infinite values in input")

    n = len(arr)
    ann_return = float(np.prod(1.0 + arr) ** (_MIN_DAYS_ONE_YEAR / n) - 1.0)

    n_years = n // _MIN_DAYS_ONE_YEAR
    trimmed = arr[-n_years * _MIN_DAYS_ONE_YEAR :]
    yearly_max_dds: list[float] = []
    for k in range(n_years):
        chunk = trimmed[k * _MIN_DAYS_ONE_YEAR : (k + 1) * _MIN_DAYS_ONE_YEAR]
        navs = pd.Series(np.concatenate([[1.0], np.cumprod(1.0 + chunk)]))
        yearly_max_dds.append(max_drawdown(navs).depth)

    avg_max_dd = float(np.mean(yearly_max_dds))
    denominator = abs(avg_max_dd - 0.10)
    if denominator <= 0:
        raise ValueError("sterling_ratio denominator collapsed to zero")
    return ann_return / denominator


def _beta_monthly(
    daily_returns: pd.Series, benchmark_returns: pd.Series
) -> tuple[np.ndarray, np.ndarray, float]:
    """Aligned monthly return arrays and their beta. Internal helper.

    Raises:
        ValueError: if fewer than 12 common months (regression undefined).
    """
    r = to_monthly_returns(daily_returns)
    bm = to_monthly_returns(benchmark_returns)
    ar, abm = align_returns(r, bm)
    if len(ar) < _MIN_MONTHS_REGRESSION:
        raise ValueError(
            f"requires at least {_MIN_MONTHS_REGRESSION} common months, got {len(ar)}"
        )
    return ar.to_numpy(dtype=float), abm.to_numpy(dtype=float), beta(ar, abm)


def treynor_ratio(
    daily_returns: pd.Series,
    benchmark_returns: pd.Series,
    risk_free_rate: float = DEFAULT_RISK_FREE_RATE,
) -> float:
    """Treynor ratio = (ann_geo_return - rf) / beta (monthly beta).

    Raises:
        ValueError: if fewer than 12 common months, NaN input, zero benchmark
            variance, or beta is ~0 (Treynor undefined).
    """
    rv, _bm, beta_m = _beta_monthly(daily_returns, benchmark_returns)
    if abs(beta_m) < 1e-10:
        raise ValueError("treynor_ratio is undefined: beta is ~0")
    geom = float(np.prod(1.0 + rv) ** (1.0 / len(rv)) - 1.0)
    ann_return = (1.0 + geom) ** _MONTHS_PER_YEAR - 1.0
    return (ann_return - risk_free_rate) / beta_m


def jensen_alpha(
    daily_returns: pd.Series,
    benchmark_returns: pd.Series,
    risk_free_rate: float = DEFAULT_RISK_FREE_RATE,
) -> float:
    """Jensen's alpha, annualized from the monthly CAPM residual.

    ``12 * (mean(r) - rf/12 - beta * (mean(bm) - rf/12))``.

    Raises:
        ValueError: if fewer than 12 common months, NaN input, or zero
            benchmark variance (beta undefined).
    """
    rv, bm, beta_m = _beta_monthly(daily_returns, benchmark_returns)
    rf_monthly = risk_free_rate / _MONTHS_PER_YEAR
    monthly_alpha = float(
        np.mean(rv) - rf_monthly - beta_m * (np.mean(bm) - rf_monthly)
    )
    return monthly_alpha * _MONTHS_PER_YEAR


@dataclass(frozen=True)
class ReturnStatistics:
    """eVestment absolute + risk-adjusted ratios (decimal fractions).

    All fields are decimal fractions or pure ratios; rf is an annual rate.
    Proficiency ratios and R-squared are added in T3A-5.
    """

    geometric_mean_monthly: float
    sterling_ratio: float
    omega_ratio: float
    treynor_ratio: float
    jensen_alpha: float
