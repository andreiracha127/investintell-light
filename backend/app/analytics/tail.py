"""Cornish-Fisher tail-VaR panel — eVestment Section VII (ported, Light convention).

Pure functions over a pandas return Series. Computes parametric (Normal) VaR,
Cornish-Fisher modified VaR (with the monotonicity clamp), Expected Tail
Loss/Return, the Rachev ratio, and the Jarque-Bera normality test.

Ported from quant_engine/tail_var_service.py (method ``cf_population_moments_v1``,
compute_tail_risk lines 115-248) but in the Light app's **positive-loss**
convention: every VaR/CVaR/ETL is a POSITIVE decimal-fraction loss magnitude
(0.05 = a 5% loss), NOT the legacy NEGATIVE return-space value. ETR is a
POSITIVE expected-gain magnitude. The legacy clamp ``min(var_m99, var_m95)`` in
negative space becomes ``max(var_m99, var_m95)`` here.

Scale contract (project-wide): all fractional quantities are decimal fractions
(0.05 = 5%), never 0-100.

Fail-loud: raises ``ValueError`` on insufficient (n < 30) or degenerate
(NaN / zero-variance) input — never returns NaN. Historical-tail fields
(``etl_95``, ``etr_95``, ``rachev_ratio``) are ``None`` (not an error) when
30 <= n < 100, because < ~5 tail observations make the historical tail
statistically meaningless; they are populated only at the n >= 100 floor.

Moments: scipy defaults (``bias=True`` population moments, excess kurtosis),
matching the legacy ``cf_population_moments_v1`` convention. Std uses ddof=1.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np
import pandas as pd
from scipy import stats as sp_stats

from app.analytics._validation import reject_nan

# Sample minimums (tiered gates, ported from tail_var_service.py lines 130, 50, 176).
TAIL_MIN_OBS = 30  # below this the panel is undefined (ValueError)
TAIL_MIN_OBS_FOR_HISTORICAL = 100  # institutional floor — guarantees >=5 tail obs at 95%

CF_METHOD_VERSION = "cf_population_moments_v1"


@dataclass(frozen=True)
class TailPanel:
    """eVestment Section VII tail-risk panel, POSITIVE-loss convention.

    All VaR/ETL fields are positive loss magnitudes; ``etr_95`` is a positive
    expected-gain magnitude. ``etl_95``/``etr_95``/``rachev_ratio`` are ``None``
    when 30 <= n < 100 (historical tail withheld below the institutional floor).
    """

    method_version: str

    # Parametric VaR (Normal distribution), positive loss magnitudes.
    var_parametric_90: float
    var_parametric_95: float
    var_parametric_99: float

    # Modified VaR (Cornish-Fisher), positive loss magnitudes, monotone in conf.
    var_modified_95: float
    var_modified_99: float

    # Jarque-Bera normality test.
    jarque_bera_stat: float
    jarque_bera_pvalue: float
    is_normal: bool  # p > 0.05

    # Historical tail metrics (n >= 100 only; else None).
    etl_95: float | None = None  # Expected Tail Loss (CVaR), positive magnitude
    etr_95: float | None = None  # Expected Tail Return (right tail), positive
    rachev_ratio: float | None = None  # ETR / ETL (both positive)


def _parametric_var_loss(mean: float, std: float, confidence: float) -> float:
    """Parametric Normal VaR as a POSITIVE loss magnitude.

    Legacy ``_parametric_var`` (tail_var_service.py lines 83-92) returns
    ``mean + z*std`` (negative). Here we negate to a positive loss:
    ``-(mean + z*std)`` where ``z = norm.ppf(1 - confidence) < 0``.
    """
    z = float(sp_stats.norm.ppf(1 - confidence))
    return -(mean + z * std)


def _cornish_fisher_var_loss(
    mean: float, std: float, skew: float, excess_kurt: float, confidence: float
) -> float:
    """Cornish-Fisher modified VaR as a POSITIVE loss magnitude.

    z_cf = z + (z^2-1)/6 * S + (z^3-3z)/24 * K - (2z^3-5z)/36 * S^2,
    then loss = -(mean + z_cf * std). Ported from
    tail_var_service._cornish_fisher_var (lines 95-112), negated to positive-loss.
    """
    z = float(sp_stats.norm.ppf(1 - confidence))
    z_cf = (
        z
        + (z**2 - 1) / 6 * skew
        + (z**3 - 3 * z) / 24 * excess_kurt
        - (2 * z**3 - 5 * z) / 36 * skew**2
    )
    return -(mean + z_cf * std)


def tail_panel(returns: pd.Series) -> TailPanel:
    """Compute the eVestment Section VII tail-risk panel from a return series.

    Args:
        returns: daily simple returns, decimal fractions (0.05 = 5%).

    Raises:
        ValueError: fewer than 30 finite returns, NaN/inf in the input, or a
            (near-)zero-variance series (tail measures undefined).
    """
    reject_nan(returns, "tail_panel")
    values = returns.to_numpy(dtype=float)
    n = int(values.size)
    if n < TAIL_MIN_OBS:
        raise ValueError(
            f"tail_panel requires at least {TAIL_MIN_OBS} returns, got {n}"
        )

    mean = float(np.mean(values))
    std = float(np.std(values, ddof=1))
    # Check std before computing higher moments to avoid scipy precision warnings
    # on a degenerate series (ported from BUG-T3-SCIPY-ORDER, tail_var_service
    # lines 142-144).
    if std < 1e-12:
        raise ValueError("tail_panel is undefined: returns have (near-)zero variance")

    skew = float(sp_stats.skew(values))
    excess_kurt = float(sp_stats.kurtosis(values))  # excess kurtosis (scipy default)

    # Parametric (Normal) VaR — positive loss magnitudes.
    var_p90 = _parametric_var_loss(mean, std, 0.90)
    var_p95 = _parametric_var_loss(mean, std, 0.95)
    var_p99 = _parametric_var_loss(mean, std, 0.99)

    # Modified (Cornish-Fisher) VaR — positive loss magnitudes.
    var_m95 = _cornish_fisher_var_loss(mean, std, skew, excess_kurt, 0.95)
    var_m99 = _cornish_fisher_var_loss(mean, std, skew, excess_kurt, 0.99)

    # Monotonicity clamp (ported from BUG-T2c-CF-MONOTONIC, tail_var_service
    # lines 158-168). The legacy ``min(var_m99, var_m95)`` selected the more
    # negative (worse) loss; in POSITIVE-loss space the worse loss is the LARGER
    # value, so we take ``max``. The 99% loss must be at least the 95% loss.
    if var_m99 < var_m95:
        var_m99 = max(var_m99, var_m95)

    # Jarque-Bera normality test (population moments are correct for JB).
    jb_stat = float(n * (skew**2 / 6 + excess_kurt**2 / 24))
    jb_pvalue = float(sp_stats.chi2.sf(jb_stat, df=2))  # survival function (BUG-T2a-JBSF)
    is_normal = jb_pvalue > 0.05

    etl_95: float | None = None
    etr_95: float | None = None
    rachev: float | None = None

    if n >= TAIL_MIN_OBS_FOR_HISTORICAL:
        sorted_returns = np.sort(values)
        # ceil tail count, matching cvar_service convention (BUG-T2a-CEIL,
        # tail_var_service line 188).
        cutoff = max(1, math.ceil(round(n * 0.05, 10)))
        # ETL: positive loss magnitude (negate the mean of the worst tail).
        etl_95 = -float(np.mean(sorted_returns[:cutoff]))
        # ETR: positive gain magnitude (mean of the symmetric right tail,
        # tail_var_service lines 207-208).
        etr_95 = float(np.mean(sorted_returns[n - cutoff:]))
        # Rachev = ETR / ETL (both positive). Undefined when ETL is non-positive
        # (a window with no losses) -> leave None (BUG-T3-RACHEV-DEGRADED).
        if etl_95 > 1e-12 and etr_95 > 1e-12:
            rachev = etr_95 / etl_95

    return TailPanel(
        method_version=CF_METHOD_VERSION,
        var_parametric_90=var_p90,
        var_parametric_95=var_p95,
        var_parametric_99=var_p99,
        var_modified_95=var_m95,
        var_modified_99=var_m99,
        jarque_bera_stat=jb_stat,
        jarque_bera_pvalue=jb_pvalue,
        is_normal=is_normal,
        etl_95=etl_95,
        etr_95=etr_95,
        rachev_ratio=rachev,
    )
