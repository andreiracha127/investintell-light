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


def _tail_mask(port_returns: np.ndarray, confidence: float, func_name: str) -> np.ndarray:
    """Boolean mask of the loss-tail scenarios (port <= the (1-c) quantile).

    Identical selection to app.analytics.historical_cvar (risk.py:109-110) so
    the aggregate ETL reconciles exactly with the F3 estimator.
    """
    if not 0 < confidence < 1:
        raise ValueError(f"{func_name}: confidence must be in (0, 1), got {confidence}")
    cutoff = float(np.quantile(port_returns, 1 - confidence))
    mask = port_returns <= cutoff
    if not mask.any():
        raise ValueError(f"{func_name} tail selection is empty")
    return mask


@dataclass(frozen=True)
class EtlRiskBudget:
    """Per-asset Expected-Shortfall (ETL/CVaR) decomposition (daily scale).

    ``portfolio_etl``: POSITIVE loss magnitude (matches historical_cvar).
    ``mcetl``: marginal contribution to ETL = −E[r_i | portfolio in tail]
        (positive when asset i loses in the portfolio tail).
    ``cetl``:  absolute contribution, w_i·mcetl_i (sums to portfolio_etl).
    ``pcetl``: percentage contribution (sums to 1.0; scale-invariant).
    """

    portfolio_etl: float
    mcetl: np.ndarray
    cetl: np.ndarray
    pcetl: np.ndarray


def etl_risk_budget(
    weights: np.ndarray, scenarios: np.ndarray, confidence: float = 0.95
) -> EtlRiskBudget:
    """Euler decomposition of historical Expected Shortfall on a T×N matrix.

    The portfolio loss tail is the set of scenarios whose portfolio return is at
    or below the (1−confidence) quantile (same rule as historical_cvar). The
    marginal ETL of asset i is the negated mean of its return over that tail, so
    by linearity Σ_i w_i·MCETL_i = −mean(portfolio tail) = portfolio_etl
    (positive). PCETL_i = w_i·MCETL_i / portfolio_etl (sums to 1).

    Raises ValueError on <10 rows, NaN/inf, a weights-length mismatch, a
    confidence outside (0, 1), an empty tail, or a non-positive portfolio ETL
    (the loss tail has non-negative mean return).
    """
    scen = _validate_scenarios(scenarios, "etl_risk_budget", _MIN_TAIL_ROWS)
    w = _validate_weights(weights, scen.shape[1], "etl_risk_budget")
    port = scen @ w
    mask = _tail_mask(port, confidence, "etl_risk_budget")
    tail_assets = scen[mask, :]            # (k, N) asset returns in the tail
    mcetl = -tail_assets.mean(axis=0)      # (N,) positive loss magnitudes
    portfolio_etl = float(-port[mask].mean())
    if portfolio_etl <= 0.0:
        raise ValueError(
            "etl_risk_budget is undefined: non-positive portfolio ETL "
            "(the loss tail has non-negative mean return)"
        )
    cetl = w * mcetl
    pcetl = cetl / portfolio_etl
    return EtlRiskBudget(
        portfolio_etl=portfolio_etl,
        mcetl=np.asarray(mcetl, dtype=float),
        cetl=np.asarray(cetl, dtype=float),
        pcetl=np.asarray(pcetl, dtype=float),
    )


def portfolio_starr(
    weights: np.ndarray,
    scenarios: np.ndarray,
    portfolio_return_ann: float,
    risk_free_rate: float,
    confidence: float = 0.95,
) -> float:
    """Portfolio STARR = annualized excess return / annualized ETL.

    ``portfolio_return_ann`` is the EXPLICIT annualized portfolio expected
    return (gate G5: by contract the caller supplies wᵀμ_BL — never a sample
    mean). The annualized ETL is the daily etl_risk_budget ETL × TRADING_DAYS.
    STARR is positive iff the annualized return exceeds the risk-free rate.

    Raises ValueError on a NaN/inf return or rf, or any condition raised by
    etl_risk_budget (short/empty tail, non-positive ETL, NaN, shape mismatch).
    """
    if not np.isfinite(portfolio_return_ann):
        raise ValueError("portfolio_starr: portfolio_return_ann must be finite")
    if not np.isfinite(risk_free_rate):
        raise ValueError("portfolio_starr: risk_free_rate must be finite")
    dec = etl_risk_budget(weights, scenarios, confidence=confidence)
    etl_ann = dec.portfolio_etl * TRADING_DAYS
    return float((portfolio_return_ann - risk_free_rate) / etl_ann)
