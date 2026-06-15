"""Tier 2 risk budgeting (pure numpy) on a T×N daily scenario matrix.

Two Euler decompositions of portfolio risk into per-asset contributions, with
their implied-return duals:

1. Variance / volatility:  MCTR_i = (Σw)_i / σ_p,  CTR_i = w_i·MCTR_i,
   PCTR_i = CTR_i / σ_p (CTR sums to σ_p; PCTR sums to 1; PCTR is identical to
   app.analytics.portfolio.risk_contributions).
   Sharpe-implied return_i = rf + Sharpe · MCTR_ann_i  (gate G5: rf + BL μ
   explicit; this module never estimates a return mean).

2. Tail / Expected Shortfall (ETL ≡ CVaR):  the Euler decomposition of the
   historical ES is the per-asset MEAN of asset returns over the scenarios that
   form the portfolio loss tail (Tasche 2002). MCETL_i / CETL_i sum EXACTLY to
   the (positive) portfolio ETL.  STARR = ann. excess return / ann. ETL.
   ETL-implied return_i = rf + STARR · MCETL_ann_i  (gate G5: rf + BL μ
   explicit).

SCALE: inputs are DAILY decimal-fraction returns (0.05 = 5%). Vol-/ES-like
outputs are at the daily scale of the input; annualize at the presentation
layer (×252 for return/ES-like, ×√252 for vol-like). PCTR/PCETL are
scale-invariant. (Same convention as risk_budgeting_service.py:26-32 and the
optimizer's TRADING_DAYS = 252 in engine.py:23.)

μ-FREE (gate G5): this module NEVER takes a sample mean of a scenario COLUMN.
The only .mean(...) calls are the ES tail kernel (tail_assets.mean(axis=0),
port[mask].mean()), which is the legitimate empirical-ES estimator, not an
expected-return estimate. Implied-return functions require an EXPLICIT
portfolio_return_ann (= wᵀμ_BL) and rf.

Fail-loud: every function raises ValueError on insufficient/degenerate/NaN
input — never returns NaN. (Matches app.analytics.risk / app.analytics.portfolio.)
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

TRADING_DAYS = 252

# Variance below this is numerical dust, not signal (matches
# app.analytics.portfolio._VARIANCE_FLOOR at portfolio.py:56). Degenerate
# zero-risk portfolios are rejected at this floor.
_VARIANCE_FLOOR = 1e-24
_MIN_SCENARIO_ROWS = 2
_MIN_TAIL_ROWS = 10  # matches app.analytics.risk._MIN_TAIL_POINTS (risk.py:20)


def _validate_scenarios(scenarios: np.ndarray, func_name: str, min_rows: int) -> np.ndarray:
    """Coerce to a finite float T×N matrix with at least *min_rows* rows."""
    scen = np.asarray(scenarios, dtype=float)
    if scen.ndim != 2:
        raise ValueError(f"{func_name} requires a T×N scenario matrix, got ndim={scen.ndim}")
    if scen.shape[0] < min_rows:
        raise ValueError(f"{func_name} requires at least {min_rows} rows, got {scen.shape[0]}")
    if scen.shape[1] < 1:
        raise ValueError(f"{func_name} requires at least 1 column, got {scen.shape[1]}")
    if not np.isfinite(scen).all():
        raise ValueError(f"{func_name} received NaN or infinite values in input; clean the data first")
    return scen


def _validate_weights(weights: np.ndarray, n: int, func_name: str) -> np.ndarray:
    w = np.asarray(weights, dtype=float).ravel()
    if w.shape[0] != n:
        raise ValueError(f"{func_name} weights length {w.shape[0]} != {n} scenario columns")
    if not np.isfinite(w).all():
        raise ValueError(f"{func_name} received NaN or infinite values in weights")
    return w


@dataclass(frozen=True)
class VarianceRiskBudget:
    """Per-asset variance/volatility decomposition (daily scale).

    ``portfolio_volatility``: daily σ_p = sqrt(wᵀΣw).
    ``mctr``: marginal contribution to volatility, (Σw)_i / σ_p.
    ``ctr``:  absolute contribution to volatility, w_i·mctr_i (sums to σ_p).
    ``pctr``: percentage contribution (sums to 1.0; scale-invariant).
    """

    portfolio_volatility: float
    mctr: np.ndarray
    ctr: np.ndarray
    pctr: np.ndarray


def variance_risk_budget(weights: np.ndarray, scenarios: np.ndarray) -> VarianceRiskBudget:
    """Euler decomposition of portfolio volatility on a T×N scenario matrix.

    Σ = sample covariance (ddof=1, matching portfolio.risk_contributions).
    σ²_p = wᵀΣw. MCTR_i = (Σw)_i / σ_p, CTR_i = w_i·MCTR_i (sums to σ_p),
    PCTR_i = CTR_i / σ_p (sums to 1).

    Raises ValueError on <2 rows, NaN/inf, a weights-length mismatch, or a
    portfolio variance at/below the numerical floor (decomposition undefined).
    """
    scen = _validate_scenarios(scenarios, "variance_risk_budget", _MIN_SCENARIO_ROWS)
    w = _validate_weights(weights, scen.shape[1], "variance_risk_budget")
    cov = np.atleast_2d(np.cov(scen, rowvar=False, ddof=1))
    sigma_w = cov @ w
    var_p = float(w @ sigma_w)
    if var_p < _VARIANCE_FLOOR:
        raise ValueError("variance_risk_budget is undefined: portfolio variance is 0")
    sigma_p = float(np.sqrt(var_p))
    mctr = sigma_w / sigma_p
    ctr = w * mctr
    pctr = ctr / sigma_p
    return VarianceRiskBudget(
        portfolio_volatility=sigma_p,
        mctr=np.asarray(mctr, dtype=float),
        ctr=np.asarray(ctr, dtype=float),
        pctr=np.asarray(pctr, dtype=float),
    )
