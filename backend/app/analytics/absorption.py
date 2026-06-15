"""Kritzman–Li (2010) absorption ratio — pure eigendecomposition diagnostic.

A single ``np.linalg.eigvalsh`` of a universe CORRELATION matrix (the kind
``app.analytics.portfolio.correlation_matrix`` produces): the fraction of total
variance absorbed by the top ``k`` eigenvectors plus the first-eigenvalue
concentration band. A high absorption ratio means a few eigenvectors explain
most of the cross-sectional variance — markets are tightly coupled (fragile /
risk-off prone).

Ported from ``correlation_regime_service.py::_compute_concentration`` (legacy
quant engine, lines 254-312), stripped of the Ledoit-Wolf shrinkage and
Marchenko-Pastur denoising that belong to the regime service; this function is
the bare concentration diagnostic so it can be unit-tested on synthetic
matrices.

Conventions (project-wide): pure numpy, no I/O, fail loud on bad input
(ValueError on non-square / asymmetric / NaN / degenerate). Ratios are decimal
fractions in [0, 1] (0.91 = 91%), never 0-100.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

# Kritzman & Li (2010) default: top k = N/5 eigenvectors (at least 1).
_DEFAULT_K_DIVISOR = 5

# First-eigenvalue concentration bands (strict >): mirror the legacy
# _compute_concentration thresholds.
_CONCENTRATION_HIGH = 0.80
_CONCENTRATION_MODERATE = 0.60

# Absorption-ratio status bands (strict >).
_ABSORPTION_CRITICAL = 0.90
_ABSORPTION_WARNING = 0.80

_SYMMETRY_ATOL = 1e-8


@dataclass(frozen=True, slots=True)
class AbsorptionResult:
    """Kritzman–Li absorption diagnostic over a correlation matrix."""

    n_assets: int
    top_k: int
    eigenvalues: tuple[float, ...]  # descending, floored at 0
    first_eigenvalue_ratio: float  # eig[0] / sum(eig), in [0, 1]
    absorption_ratio: float  # sum(eig[:k]) / sum(eig), in [0, 1]
    concentration_status: str  # "diversified" | "moderate_concentration" | "high_concentration"
    absorption_status: str  # "normal" | "warning" | "critical"


def absorption_ratio(
    corr_matrix: np.ndarray,
    *,
    top_k: int | None = None,
) -> AbsorptionResult:
    """Compute the Kritzman–Li absorption ratio of a correlation matrix.

    Parameters
    ----------
    corr_matrix : np.ndarray
        Square, symmetric (N×N) correlation matrix — typically the
        ``.to_numpy()`` of ``app.analytics.portfolio.correlation_matrix`` on the
        aligned returns frame. Must be finite.
    top_k : int | None
        Number of leading eigenvectors to sum for the absorption ratio.
        Defaults to ``max(1, N // 5)`` (Kritzman & Li 2010). When given it must
        satisfy ``1 <= top_k <= N``.

    Raises
    ------
    ValueError
        If the matrix is not square, not symmetric, contains NaN/inf, has fewer
        than 2 assets, has non-positive total variance (trace), or ``top_k`` is
        out of range. Never returns NaN (fail-loud contract).
    """
    matrix = np.asarray(corr_matrix, dtype=float)
    if matrix.ndim != 2 or matrix.shape[0] != matrix.shape[1]:
        raise ValueError(
            f"absorption_ratio requires a square matrix, got shape {matrix.shape}"
        )
    n = matrix.shape[0]
    if n < 2:
        raise ValueError(f"absorption_ratio requires at least 2 assets, got {n}")
    if not np.isfinite(matrix).all():
        raise ValueError(
            "absorption_ratio received NaN or infinite values; clean the matrix first"
        )
    if not np.allclose(matrix, matrix.T, atol=_SYMMETRY_ATOL):
        raise ValueError("absorption_ratio requires a symmetric correlation matrix")

    k = max(1, n // _DEFAULT_K_DIVISOR) if top_k is None else top_k
    if not 1 <= k <= n:
        raise ValueError(
            f"absorption_ratio top_k must be in [1, {n}], got {top_k}"
        )

    # Single eigendecomposition of the symmetric matrix.
    eigenvalues = np.linalg.eigvalsh(matrix)
    eigenvalues = np.sort(eigenvalues)[::-1]  # descending
    eigenvalues = np.maximum(eigenvalues, 0.0)  # numerical floor (PSD)

    total = float(eigenvalues.sum())
    if total <= 0.0:
        raise ValueError(
            "absorption_ratio is undefined: non-positive total variance (trace)"
        )

    first_ratio = float(eigenvalues[0] / total)
    absorption = float(eigenvalues[:k].sum() / total)

    if first_ratio > _CONCENTRATION_HIGH:
        concentration_status = "high_concentration"
    elif first_ratio > _CONCENTRATION_MODERATE:
        concentration_status = "moderate_concentration"
    else:
        concentration_status = "diversified"

    if absorption > _ABSORPTION_CRITICAL:
        absorption_status = "critical"
    elif absorption > _ABSORPTION_WARNING:
        absorption_status = "warning"
    else:
        absorption_status = "normal"

    return AbsorptionResult(
        n_assets=n,
        top_k=k,
        eigenvalues=tuple(float(e) for e in eigenvalues),
        first_eigenvalue_ratio=first_ratio,
        absorption_ratio=absorption,
        concentration_status=concentration_status,
        absorption_status=absorption_status,
    )
