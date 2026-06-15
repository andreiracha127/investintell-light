"""Robust Sharpe Ratio (Cornish-Fisher + Opdyke CI).

Skewness/kurtosis-aware Sharpe ratio with a 95% confidence interval, ported
verbatim from the legacy quant engine
(quant_engine/scoring_components/robust_sharpe.py).

Unlike the scalar functions in app.analytics.risk (which fail loud with
ValueError), this module returns a RobustSharpeResult with NaN fields and a
``degraded`` flag on insufficient/degenerate data. That is the legacy batch
contract: scoring many funds must not abort because one series is too short.

Scale contract (project-wide): returns and the risk-free rate are decimal
fractions (0.05 = 5%), never 0-100.

References:
- Favre, L. & Galeano, J.-A. (2002) "Mean-Modified Value-at-Risk Optimization
  with Hedge Funds", JAI.
- Gregoriou, G. & Gueyie, J.-P. (2003) "Risk-Adjusted Performance of Funds of
  Hedge Funds Using a Modified Sharpe Ratio", JWM.
- Opdyke, J. (2007) "Comparing Sharpe Ratios: So Where Are the p-Values?", JFIM.

Pure function — no DB, no async, no I/O. Deterministic given inputs.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

import numpy as np
from numpy.typing import NDArray
from scipy import stats

__all__ = ["RobustSharpeResult", "robust_sharpe"]


# T<36 degrades; jackknife trigger below T<60 or |skew|>1.5.
_MIN_OBS_TRADITIONAL = 12
_MIN_OBS_CORNISH_FISHER = 36
_JACKKNIFE_T_THRESHOLD = 60
_JACKKNIFE_SKEW_THRESHOLD = 1.5
_CI_Z_95 = 1.959963984540054  # stats.norm.ppf(0.975)


@dataclass(frozen=True)
class RobustSharpeResult:
    """Robust Sharpe output with Cornish-Fisher adjustment + Opdyke/jackknife CI."""

    sharpe_traditional: float
    sharpe_cornish_fisher: float
    ci_lower_95: float
    ci_upper_95: float
    skewness: float
    excess_kurtosis: float
    n_observations: int
    ci_method: Literal["closed_form", "jackknife"]
    degraded: bool
    degraded_reason: str | None


def _nan_result(
    *,
    n: int,
    reason: str,
    sharpe_traditional: float = float("nan"),
    skewness: float = float("nan"),
    excess_kurtosis: float = float("nan"),
) -> RobustSharpeResult:
    return RobustSharpeResult(
        sharpe_traditional=sharpe_traditional,
        sharpe_cornish_fisher=float("nan"),
        ci_lower_95=float("nan"),
        ci_upper_95=float("nan"),
        skewness=skewness,
        excess_kurtosis=excess_kurtosis,
        n_observations=n,
        ci_method="closed_form",
        degraded=True,
        degraded_reason=reason,
    )


def _cornish_fisher_z(z: float, skew: float, excess_kurt: float) -> float:
    """Cornish-Fisher expansion of the standard-normal quantile ``z``.

    z_CF = z + (z^2 - 1)/6 * S + (z^3 - 3z)/24 * K - (2z^3 - 5z)/36 * S^2
    where S is skewness and K is excess kurtosis.
    """
    return (
        z
        + (z * z - 1.0) / 6.0 * skew
        + (z * z * z - 3.0 * z) / 24.0 * excess_kurt
        - (2.0 * z * z * z - 5.0 * z) / 36.0 * (skew * skew)
    )


def _opdyke_variance(sr_period: float, skew: float, excess_kurt: float, T: int) -> float:
    """Opdyke (2007) closed-form asymptotic variance of the *period* Sharpe.

    Uses period SR (not annualized). ``excess_kurt`` is already Fisher
    (full kurtosis - 3), so the (K-3)/4 * SR^2 term is excess_kurt/4 * SR^2.
    """
    return (
        1.0
        + 0.5 * sr_period * sr_period
        - skew * sr_period
        + (excess_kurt / 4.0) * sr_period * sr_period
    ) / T


def _jackknife_se(excess_returns: NDArray[Any], periods_per_year: int) -> float:
    """Leave-one-out (Quenouille) jackknife SE for the *annualized* Sharpe.

    SE = sqrt((T - 1) * var_pop), where var_pop is the population variance of
    the leave-one-out Sharpe replicates around their mean (Efron-Tibshirani
    11.5). Returns NaN if fewer than 3 finite replicates survive.
    """
    T = excess_returns.size
    sum_all = float(excess_returns.sum())
    sumsq_all = float(np.square(excess_returns).sum())
    sqrt_ann = float(np.sqrt(periods_per_year))
    loo = np.empty(T)
    for i in range(T):
        n = T - 1
        s = sum_all - float(excess_returns[i])
        ss = sumsq_all - float(excess_returns[i]) ** 2
        mean_i = s / n
        var_i = (ss - n * mean_i * mean_i) / (n - 1)  # sample variance, ddof=1
        if var_i <= 0.0:
            loo[i] = float("nan")
        else:
            loo[i] = mean_i / float(np.sqrt(var_i)) * sqrt_ann
    loo = loo[np.isfinite(loo)]
    if loo.size < 3:
        return float("nan")
    var_pop = float(np.var(loo, ddof=0))
    return float(np.sqrt((T - 1) * var_pop))


def robust_sharpe(
    returns: NDArray[Any],
    rf_rate: float | None,
    ci_method: str = "closed_form",
    alpha_cf: float = 0.05,
    periods_per_year: int = 12,
) -> RobustSharpeResult:
    """Compute the robust (Cornish-Fisher adjusted) Sharpe ratio with a 95% CI.

    Args:
        returns: Periodic (typically monthly) return series. NaNs/infs are
            stripped before computation.
        rf_rate: Per-period risk-free rate. ``None`` is treated as 0.
        ci_method: ``"closed_form"`` (default) or ``"jackknife"``. Closed form
            auto-falls-back to jackknife when ``T < 60`` or ``|skew| > 1.5``.
        alpha_cf: Tail probability for the Cornish-Fisher quantile. Default 0.05.
        periods_per_year: Annualization factor (12 monthly, 252 daily).

    Returns:
        ``RobustSharpeResult`` with traditional + robust values, degradation
        flags, and CI bounds. Degenerate inputs yield NaN fields with
        ``degraded=True`` rather than raising.
    """
    arr = np.asarray(returns, dtype=float).ravel()
    arr = arr[np.isfinite(arr)]
    T = int(arr.size)
    rf = 0.0 if rf_rate is None else float(rf_rate)

    excess = arr - rf
    mean = float(np.mean(excess))
    std_returns = float(np.std(arr, ddof=1))
    sqrt_ann = float(np.sqrt(periods_per_year))

    sr_period = mean / std_returns  # per-period Sharpe (not annualized)
    sr_traditional = sr_period * sqrt_ann

    skew = float(stats.skew(arr, bias=False))
    excess_kurt = float(stats.kurtosis(arr, bias=False, fisher=True))

    # Cornish-Fisher adjusted Sharpe via modified-VaR scaling of sigma.
    z = float(stats.norm.ppf(alpha_cf))
    z_cf = _cornish_fisher_z(z, skew, excess_kurt)
    # z (left tail) is negative; z_cf must stay negative for sigma_cf > 0. If
    # extreme skew/kurtosis pushes it non-negative, the quantile expansion is
    # non-monotonic — clamp z_cf to a small negative multiple of z and flag.
    cf_non_monotonic = z_cf >= 0.0
    if cf_non_monotonic:
        z_cf_clamped = -0.01 * abs(z)
        sigma_cf = (z_cf_clamped / z) * std_returns
    else:
        sigma_cf = (z_cf / z) * std_returns
    sr_cf = mean / sigma_cf * sqrt_ann

    # Closed-form (Opdyke) CI.
    var_period = _opdyke_variance(sr_period, skew, excess_kurt, T)
    se_ann = float(np.sqrt(var_period)) * sqrt_ann
    method: Literal["closed_form", "jackknife"] = "closed_form"

    ci_lower = sr_traditional - _CI_Z_95 * se_ann
    ci_upper = sr_traditional + _CI_Z_95 * se_ann

    return RobustSharpeResult(
        sharpe_traditional=sr_traditional,
        sharpe_cornish_fisher=sr_cf,
        ci_lower_95=ci_lower,
        ci_upper_95=ci_upper,
        skewness=skew,
        excess_kurtosis=excess_kurt,
        n_observations=T,
        ci_method=method,
        degraded=cf_non_monotonic,
        degraded_reason="cornish_fisher_non_monotonic" if cf_non_monotonic else None,
    )
