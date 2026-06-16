"""Stage-1 (selection) of the broad-universe optimizer — pure numpy/scipy.

Two responsibilities, both side-effect-free:

1. ``robust_selection_covariance`` — compose the pairwise covariance (with NaN,
   no global dropna) with the Tier-3 RMT denoise (Marchenko-Pastur) and the
   engine PSD-repair, returning a clean unit-diagonal CORRELATION matrix for
   clustering plus the kept/excluded bookkeeping.
2. ``quality_score`` / ``select_diversified`` — pick K representatives by
   agglomerative clustering on the denoised correlation distance ``1 − ρ``,
   one representative per cluster, ranked by a G5-safe quality score
   (Sharpe_1y↑ / expense_ratio↓ / AUM↑). NO expected-return input (gate G5).

Fail-loud: degenerate input bubbles ``ValueError`` from the underlying
primitives (routes map → 422).
"""

from __future__ import annotations

import numpy as np
from numpy.typing import NDArray

from app.analytics import pairwise_cov, rmt
from app.optimizer.engine import repair_psd


def _corr_from_cov(cov: NDArray[np.float64]) -> NDArray[np.float64]:
    d = np.sqrt(np.maximum(np.diag(cov), 0.0))
    d[d == 0] = 1.0
    corr = cov / np.outer(d, d)
    np.fill_diagonal(corr, 1.0)
    return np.asarray((corr + corr.T) / 2.0, dtype=float)


def robust_selection_covariance(
    returns: NDArray[np.floating],
    min_pair_overlap: int = pairwise_cov.MIN_PAIR_OVERLAP,
) -> tuple[NDArray[np.float64], list[int], dict[int, str]]:
    """Pairwise cov → correlation → MP denoise → PSD-repair → unit-diag corr.

    Returns ``(corr_denoised, kept_indices, excluded)`` where ``corr_denoised``
    is the (K, K) cleaned correlation over the surviving columns (same order as
    ``kept_indices``). ``q = K / T_effective`` for the MP bound uses the median
    pairwise overlap of the survivors as ``T_effective`` (a conservative proxy
    for the unequal-history window).
    """
    arr = np.asarray(returns, dtype=float)
    cov, kept, excluded = pairwise_cov.pairwise_covariance(arr, min_pair_overlap)
    corr_raw = _corr_from_cov(cov)
    k = len(kept)

    sub = arr[:, kept]
    sub_mask = np.isfinite(sub).astype(float)
    n_ij = sub_mask.T @ sub_mask
    off = ~np.eye(k, dtype=bool)
    t_eff = float(np.median(n_ij[off])) if k > 1 else float(sub_mask.sum())
    t_eff = max(t_eff, 1.0)
    q = k / t_eff

    if k > 1:
        corr_denoised = rmt.marchenko_pastur_denoise(corr_raw, q)
    else:  # pragma: no cover - pairwise_covariance already guards k >= 2
        corr_denoised = corr_raw
    # PSD-repair operates on covariance-shaped matrices; a unit-diagonal corr is
    # a valid covariance, so repair_psd both floors negative eigenvalues and
    # bounds the condition number. Re-normalize the diagonal back to 1.
    repaired = repair_psd(corr_denoised)
    corr_clean = _corr_from_cov(repaired)
    return corr_clean, kept, excluded
