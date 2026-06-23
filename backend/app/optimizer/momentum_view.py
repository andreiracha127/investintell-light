"""Category-level momentum view for the regime_aware (COMBO) BL layer.

Ported from the calibrated harness ``_category_mu`` (local_fund_backtest.py): the
Level-1 category BL posterior μ = equilibrium π (π = DELTA_MARKET·Σ·prior) plus
ONE relative top-minus-bottom 12-1 momentum view over the RISK categories,
subordinate to the live gate — no risk-on momentum tilt when the gate is
``risk_off``.

This is a SERVICE, not a CRUD view: production momentum views did not exist (the
Builder only accepts request-time views); the regime_aware motor calls this each
rebalance to produce the μ that the BL max-utility solve consumes. Causal /
gate-G5 safe: the momentum score is the 12-1 cumulative return (skip the most
recent ``MOM_SKIP`` days) over the proxy returns; σ is the Ledoit-Wolf shrinkage
over the trailing ``window``. Pure: no I/O, no logging.

The view is the SAME single relative innovation as the harness — top-frac minus
bottom-frac of the cross-sectional momentum z-score, predicted to out-perform by
``VIEW_SPREAD``/yr over equilibrium, with Idzorek confidence ``VIEW_CONF``.
"""

from __future__ import annotations

import numpy as np

from app.optimizer import black_litterman as bl
from app.optimizer import engine
from app.optimizer.mandate import DELTA_MARKET

# Calibrated constants (harness parity, local_fund_backtest.py:207-217).
MOM_GROUPS: frozenset[str] = frozenset(
    {"equity", "thematic", "fixed_income", "alternatives"}
)
VIEW_FRAC = 0.25      # top-frac vs bottom-frac for the relative view
VIEW_SPREAD = 0.04    # predicted top-minus-bottom out-performance, per year
VIEW_CONF = 0.50      # Idzorek confidence on the relative momentum view
TAU = 0.05
DEFAULT_WINDOW = 504  # trailing days for the Ledoit-Wolf Σ (2y)
MOM_LOOKBACK = 252    # 12 months
MOM_SKIP = 21         # skip the most recent month (the "12-1" in 12-1 momentum)
MIN_RISK = 4          # need >= 4 risk categories for the cross-sectional view


def _momentum_score(returns: np.ndarray, cols: list[int]) -> np.ndarray:
    """12-1 momentum (causal): cumulative return over the window ENDING ``MOM_SKIP``
    days before the most recent row of ``returns`` (whose last row is the latest
    known return — execution is at the next row). Best OOS spec of the harness;
    vol-adjustment destroyed the skill, so the raw cumulative return is used."""
    t = returns.shape[0]
    lo = max(0, t - MOM_LOOKBACK)
    hi = t - MOM_SKIP
    if hi <= lo:
        return np.zeros(len(cols), dtype=float)
    seg = np.nan_to_num(returns[lo:hi][:, cols], nan=0.0)
    return np.prod(1.0 + seg, axis=0) - 1.0


def _top_bottom_view(
    pi_sub: np.ndarray, score: np.ndarray, frac: float, spread: float
) -> tuple[np.ndarray, np.ndarray]:
    """One RELATIVE view: top-frac minus bottom-frac of ``score``, predicted to beat
    by ``spread``/yr over equilibrium. Preserves the equilibrium level — only the
    transversal spread is the innovation Q − P·π = spread."""
    n = len(score)
    k = max(1, int(round(n * frac)))
    order = np.argsort(score)
    bottom, top = order[:k], order[-k:]
    p = np.zeros((1, n))
    p[0, top] = 1.0 / len(top)
    p[0, bottom] = -1.0 / len(bottom)
    q = np.array([float(p[0] @ pi_sub + spread)])
    return p, q


def category_momentum_mu(
    returns: np.ndarray,
    groups: list[str],
    prior: np.ndarray,
    gate_state: str | None,
    *,
    window: int = DEFAULT_WINDOW,
    delta_market: float = DELTA_MARKET,
    use_views: bool = True,
    sigma: np.ndarray | None = None,
) -> np.ndarray:
    """Per-proxy BL posterior μ over the category proxies (annualized-consistent
    with ``returns``' Σ — the caller keeps μ and Σ in the same units).

    ``returns`` is the trailing daily-return matrix (T×n) whose LAST row is the
    most recent known return; ``groups`` is the per-proxy group label; ``prior``
    is the market-prior weight vector (sum 1) used for the equilibrium. The
    momentum view fires only when the gate is NOT ``risk_off``, ``use_views`` is
    True, and at least ``MIN_RISK`` proxies are in ``MOM_GROUPS``; otherwise μ = π.
    Returns a length-n vector (empty input -> empty).
    """
    returns = np.asarray(returns, dtype=float)
    if returns.ndim != 2:
        raise ValueError(f"returns must be 2-D (T×n), got ndim={returns.ndim}")
    n = returns.shape[1]
    prior = np.asarray(prior, dtype=float).ravel()
    if n == 0:
        return np.zeros(0, dtype=float)
    if prior.shape != (n,) or len(groups) != n:
        raise ValueError(
            f"groups ({len(groups)}) / prior ({prior.shape}) must match returns "
            f"columns ({n})"
        )
    if sigma is None:
        win = np.nan_to_num(returns[-window:], nan=0.0)
        sigma = engine.sigma_ledoit_wolf(win)
    else:
        sigma = np.asarray(sigma, dtype=float)
        if sigma.shape != (n, n):
            raise ValueError(f"sigma is {sigma.shape}, expected ({n}, {n})")
    pi = np.asarray(bl.equilibrium(sigma, prior, delta=delta_market), dtype=float)
    if not use_views or (gate_state or "").lower() == "risk_off":
        return pi
    risk = [k for k, g in enumerate(groups) if g in MOM_GROUPS]
    if len(risk) < MIN_RISK:
        return pi
    score = _momentum_score(returns, risk)
    z = np.clip((score - score.mean()) / (score.std() + 1e-9), -2.0, 2.0)
    p_sub, q_vec = _top_bottom_view(pi[np.array(risk)], z, VIEW_FRAC, VIEW_SPREAD)
    p_mat = np.zeros((1, n))
    p_mat[0, risk] = p_sub[0]
    omega = bl.omega_idzorek(p_mat, sigma, [VIEW_CONF], tau=TAU)
    mu_bl, _ = bl.posterior(sigma, pi, p_mat, q_vec, omega, tau=TAU)
    return np.asarray(mu_bl, dtype=float)
