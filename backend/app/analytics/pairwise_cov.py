"""Pairwise covariance over a returns matrix WITH NaN — pure numpy, no I/O.

The Stage-1 (selection) covariance estimator. Unlike a global ``dropna`` (which
collapses the common-history window to the youngest asset), this computes each
pair's covariance on THAT pair's overlapping observations, vectorized via an
availability mask — no explicit per-pair loop.

Demeaned pairwise covariance: with ``R0 = R`` (NaN→0) and ``M`` the binary
presence mask (1 where observed), ``n_ij = MᵀM`` (overlap per pair),
``μ = (R0ᵀM) / n_ij`` (pairwise means), and
``cov_ij = (R0ᵀR0) / n_ij − μ_ij · μ_jiᵀ`` (1/n convention, matches
``np.cov(..., bias=True)`` on a fully-observed matrix).

Fail-loud: a column whose MEDIAN pairwise overlap is below ``min_pair_overlap``
is EXCLUDED with a structured reason (never silently kept); the covariance is
re-built on the surviving columns. Fewer than 2 survivors raises ``ValueError``
(routes map → 422). Scale contract: returns are decimal fractions.
"""

from __future__ import annotations

import numpy as np
from numpy.typing import NDArray

MIN_PAIR_OVERLAP = 252  # ~1 trading year (design §8)


def _pairwise_raw(
    r: NDArray[np.float64], mask: NDArray[np.float64]
) -> tuple[NDArray[np.float64], NDArray[np.float64]]:
    """Return (cov, overlap_counts) for the given (NaN→0) matrix + mask."""
    r0 = np.where(mask > 0, r, 0.0)
    n_ij = mask.T @ mask  # (N, N) overlap counts per pair
    safe = np.where(n_ij > 0, n_ij, 1.0)
    sum_prod = r0.T @ r0  # (N, N) Σ rᵢ·rⱼ over the overlap
    sum_i = r0.T @ mask  # (N, N): row i = Σ rᵢ where j is present
    mean_ij = sum_i / safe  # μ_ij (mean of i over the (i,j) overlap)
    cov = sum_prod / safe - mean_ij * mean_ij.T
    cov = (cov + cov.T) / 2.0
    return np.asarray(cov, dtype=float), np.asarray(n_ij, dtype=float)


def pairwise_covariance(
    returns: NDArray[np.floating], min_pair_overlap: int = MIN_PAIR_OVERLAP
) -> tuple[NDArray[np.float64], list[int], dict[int, str]]:
    """Pairwise covariance of a (T, N) returns matrix with NaN.

    Parameters
    ----------
    returns : (T, N) array; NaN marks a missing observation (no dropna).
    min_pair_overlap : minimum overlap (rows) for a column's MEDIAN pairwise
        overlap; columns below it are excluded.

    Returns
    -------
    (cov, kept_indices, excluded) where ``cov`` is the (K, K) pairwise
    covariance over the surviving columns (in their original order),
    ``kept_indices`` are the surviving 0-based column indices, and ``excluded``
    maps an excluded column index → a human reason.

    Raises
    ------
    ValueError : input is not 2-D, or fewer than 2 viable columns survive.
    """
    arr = np.asarray(returns, dtype=float)
    if arr.ndim != 2:
        raise ValueError(f"returns must be a (T, N) matrix, got ndim={arr.ndim}")
    t, n = arr.shape
    if n < 2:
        raise ValueError("at least 2 assets are required for a covariance")
    if min_pair_overlap < 1:
        raise ValueError(f"min_pair_overlap must be >= 1, got {min_pair_overlap}")

    mask = np.isfinite(arr).astype(float)
    _, n_ij = _pairwise_raw(arr, mask)

    # Per-column viability: the MEDIAN of its off-diagonal pairwise overlaps.
    excluded: dict[int, str] = {}
    kept: list[int] = []
    off_mask = ~np.eye(n, dtype=bool)
    for i in range(n):
        overlaps = n_ij[i][off_mask[i]]
        median_overlap = float(np.median(overlaps)) if overlaps.size else 0.0
        if median_overlap < min_pair_overlap:
            excluded[i] = (
                f"median pairwise overlap {median_overlap:.0f} < "
                f"{min_pair_overlap} — short-history fund excluded"
            )
        else:
            kept.append(i)

    if len(kept) < 2:
        raise ValueError(
            f"pairwise covariance needs at least 2 funds with sufficient overlap; "
            f"{len(kept)} survived (min_pair_overlap={min_pair_overlap}) — "
            "widen the window or relax the filters"
        )

    sub = arr[:, kept]
    sub_mask = np.isfinite(sub).astype(float)
    cov, _ = _pairwise_raw(sub, sub_mask)
    return cov, kept, excluded
