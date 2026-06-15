"""Random-Matrix-Theory (RMT) primitives — pure numpy, no I/O.

The SINGLE home for the covariance/correlation cleaning math shared across the
optimizer and the correlation-regime service:

* ``ledoit_wolf_constant_correlation`` — Ledoit & Wolf (2003) shrinkage toward
  a CONSTANT-CORRELATION target F (F_ij = r̄·√(S_ii·S_jj)). Unlike
  ``sklearn.covariance.LedoitWolf`` (scaled-identity target), this preserves
  cross-asset dependence — essential for short stress windows.
* ``marchenko_pastur_denoise`` — flatten eigenvalues below the MP upper bound
  λ₊ = (1+√q)² to their average, then renormalize to a unit-diagonal
  correlation matrix.
* ``absorption_ratio`` — Kritzman & Li (2010): fraction of total variance
  absorbed by the top-k eigenvalues (k = N/5, ≥1, unless overridden). This is
  the canonical absorption primitive; the Tier-2 absorption work (T2E) must
  import THIS function rather than re-deriving it.
* ``mp_signal_eigenvalues`` — count eigenvalues above λ₊ (the "signal" count)
  and return (count, λ₊).

Scale contract: correlations and ratios are decimal fractions (0.20 = 20%).
Fail-loud: degenerate/NaN input raises ``ValueError`` (routes map → 422).
"""

from __future__ import annotations

import numpy as np
from numpy.typing import NDArray


def ledoit_wolf_constant_correlation(
    returns: NDArray[np.floating],
) -> tuple[NDArray[np.float64], float]:
    """Constant-correlation Ledoit-Wolf 2003 shrinkage.

    Parameters
    ----------
    returns : (T, N) array of returns (de-meaning handled internally).

    Returns
    -------
    (shrunk_covariance, shrinkage_intensity_delta) — δ ∈ [0, 1].

    Ported from legacy correlation_regime_service._ledoit_wolf_constant_correlation
    (1/T sample-covariance convention per the LW paper).
    """
    arr = np.asarray(returns, dtype=float)
    if arr.ndim != 2:
        raise ValueError(f"returns must be a (T, N) matrix, got ndim={arr.ndim}")
    if not np.isfinite(arr).all():
        raise ValueError("returns contain NaN/inf — refusing to estimate covariance")
    t, n = arr.shape
    if t < 2 or n < 2:
        raise ValueError(f"need at least 2 rows and 2 columns, got shape {arr.shape}")

    x = arr - arr.mean(axis=0, keepdims=True)
    s = (x.T @ x) / t  # 1/T convention (LW paper)

    var = np.diag(s).copy()
    std = np.sqrt(np.maximum(var, 1e-20))
    std_outer = np.outer(std, std)

    r = s / std_outer
    np.fill_diagonal(r, 1.0)
    mask = ~np.eye(n, dtype=bool)
    r_bar = float(r[mask].mean())

    f = r_bar * std_outer
    np.fill_diagonal(f, var)

    x2 = x ** 2
    pi_mat = (x2.T @ x2) / t - s ** 2
    pi_hat = float(pi_mat.sum())

    rho_diag = float(np.sum(np.diag(pi_mat)))
    x3 = x ** 3
    term1 = (x3.T @ x) / t - var[:, None] * s
    term2 = (x.T @ x3) / t - s * var[None, :]
    std_ratio_ji = std[None, :] / std[:, None]
    std_ratio_ij = std[:, None] / std[None, :]
    rho_off_mat = (r_bar / 2.0) * (std_ratio_ji * term1 + std_ratio_ij * term2)
    np.fill_diagonal(rho_off_mat, 0.0)
    rho_hat = rho_diag + float(rho_off_mat.sum())

    gamma_hat = float(np.sum((f - s) ** 2))
    if gamma_hat < 1e-12:
        delta = 0.0
    else:
        kappa = (pi_hat - rho_hat) / gamma_hat
        delta = float(np.clip(kappa / t, 0.0, 1.0))

    shrunk = delta * f + (1.0 - delta) * s
    return np.asarray((shrunk + shrunk.T) / 2.0, dtype=float), delta


def marchenko_pastur_denoise(
    corr_matrix: NDArray[np.floating], q: float
) -> NDArray[np.float64]:
    """Flatten sub-MP eigenvalues to their mean; return a unit-diagonal corr.

    ``q = N / T``. Ported from legacy _marchenko_pastur_denoise (clamps
    eigenvalues ≥ 0 before reconstruction to guarantee PSD output).
    """
    c = np.asarray(corr_matrix, dtype=float)
    if c.ndim != 2 or c.shape[0] != c.shape[1] or c.shape[0] == 0:
        raise ValueError(f"corr_matrix must be a non-empty square matrix, got {c.shape}")
    if not np.isfinite(c).all():
        raise ValueError("corr_matrix contains NaN/inf")
    if q <= 0:
        raise ValueError(f"q must be > 0 (= N/T), got {q}")

    eigenvalues, eigenvectors = np.linalg.eigh(c)
    idx = np.argsort(eigenvalues)[::-1]
    eigenvalues = eigenvalues[idx]
    eigenvectors = eigenvectors[:, idx]

    lambda_plus = (1 + np.sqrt(q)) ** 2
    noise_mask = eigenvalues < lambda_plus
    if noise_mask.any():
        eigenvalues[noise_mask] = float(np.mean(eigenvalues[noise_mask]))
    eigenvalues = np.maximum(eigenvalues, 0.0)

    denoised = eigenvectors @ np.diag(eigenvalues) @ eigenvectors.T
    d = np.sqrt(np.diag(denoised))
    d[d == 0] = 1.0
    denoised = denoised / np.outer(d, d)
    np.fill_diagonal(denoised, 1.0)
    return np.asarray((denoised + denoised.T) / 2.0, dtype=float)


def absorption_ratio(
    corr_matrix: NDArray[np.floating], k: int | None = None
) -> float:
    """Kritzman & Li (2010) absorption ratio: top-k eigenvalues / total.

    Default k = max(1, N // 5). Operates on a correlation (or covariance)
    matrix. This is the canonical absorption primitive (T2E imports it).
    """
    c = np.asarray(corr_matrix, dtype=float)
    if c.ndim != 2 or c.shape[0] != c.shape[1] or c.shape[0] == 0:
        raise ValueError(f"corr_matrix must be a non-empty square matrix, got {c.shape}")
    if not np.isfinite(c).all():
        raise ValueError("corr_matrix contains NaN/inf")
    n = c.shape[0]
    if k is None:
        k = max(1, n // 5)
    if not 1 <= k <= n:
        raise ValueError(f"k must be in [1, {n}], got {k}")

    eigenvalues = np.sort(np.maximum(np.linalg.eigvalsh(c), 0.0))[::-1]
    total = float(eigenvalues.sum())
    if total < 1e-12:
        return 1.0
    return float(eigenvalues[:k].sum() / total)


def mp_signal_eigenvalues(
    corr_matrix: NDArray[np.floating], q: float
) -> tuple[int, float]:
    """Count eigenvalues above the MP bound λ₊ = (1+√q)²; return (count, λ₊)."""
    c = np.asarray(corr_matrix, dtype=float)
    if c.ndim != 2 or c.shape[0] != c.shape[1] or c.shape[0] == 0:
        raise ValueError(f"corr_matrix must be a non-empty square matrix, got {c.shape}")
    if not np.isfinite(c).all():
        raise ValueError("corr_matrix contains NaN/inf")
    if q <= 0:
        raise ValueError(f"q must be > 0 (= N/T), got {q}")
    lambda_plus = (1 + np.sqrt(q)) ** 2
    eigenvalues = np.maximum(np.linalg.eigvalsh(c), 0.0)
    return int(np.sum(eigenvalues > lambda_plus)), float(lambda_plus)
