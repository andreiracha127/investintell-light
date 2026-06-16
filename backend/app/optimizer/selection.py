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

from dataclasses import dataclass

import numpy as np
from numpy.typing import NDArray
from scipy.cluster.hierarchy import fcluster, linkage
from scipy.spatial.distance import squareform

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


# Default quality-score weights (sum to 1). Sharpe dominates; expense/AUM tie.
_W_SHARPE = 0.5
_W_EXPENSE = 0.25
_W_AUM = 0.25
_NEUTRAL = 0.5


def _minmax(values: list[float | None], *, invert: bool) -> NDArray[np.float64]:
    """Min-max normalize a signal to [0, 1]; missing → neutral 0.5.

    ``invert=True`` flips the scale (lower raw value ⇒ higher score, e.g. the
    expense ratio). A degenerate signal (all equal / all missing) maps every
    present entry to the neutral 0.5 so it neither helps nor hurts.
    """
    arr = np.array(
        [np.nan if v is None else float(v) for v in values], dtype=float
    )
    present = np.isfinite(arr)
    out = np.full(arr.shape, _NEUTRAL, dtype=float)
    if present.sum() < 2:
        return out
    lo = float(arr[present].min())
    hi = float(arr[present].max())
    if hi - lo < 1e-12:
        return out
    norm = (arr[present] - lo) / (hi - lo)
    if invert:
        norm = 1.0 - norm
    out[present] = norm
    return out


def quality_score(
    metrics: list[dict[str, float | None]],
    *,
    w_sharpe: float = _W_SHARPE,
    w_expense: float = _W_EXPENSE,
    w_aum: float = _W_AUM,
) -> NDArray[np.float64]:
    """G5-safe per-fund quality score in [0, 1].

    ``metrics[i]`` carries ``sharpe_1y`` / ``expense_ratio`` / ``aum_usd``
    (any may be ``None``). The score combines normalized Sharpe (↑), inverted
    expense (↓ is better), and AUM (↑). NO expected-return / sample-mean input
    is consumed (gate G5).
    """
    if not metrics:
        raise ValueError("metrics must be non-empty")
    s_sharpe = _minmax([m.get("sharpe_1y") for m in metrics], invert=False)
    s_expense = _minmax([m.get("expense_ratio") for m in metrics], invert=True)
    s_aum = _minmax([m.get("aum_usd") for m in metrics], invert=False)
    return np.asarray(
        w_sharpe * s_sharpe + w_expense * s_expense + w_aum * s_aum, dtype=float
    )


@dataclass(frozen=True)
class SelectionResult:
    """Stage-1 output: chosen representatives + cluster/score bookkeeping.

    ``selected`` are 0-based indices INTO the correlation matrix passed to
    ``select_diversified`` (i.e. positions within the kept/survivor set).
    ``cluster_of`` maps each selected index → its cluster label;
    ``score_of`` maps it → its quality score.
    """

    selected: list[int]
    cluster_of: dict[int, int]
    score_of: dict[int, float]


def select_diversified(
    corr_denoised: NDArray[np.floating],
    scores: NDArray[np.floating],
    k: int,
) -> SelectionResult:
    """Pick ≤ K representatives: 1 per cluster, max quality within the cluster.

    Agglomerative (average-linkage) clustering on the distance ``d = 1 − ρ``
    over the denoised correlation, cut into ``min(k, N)`` clusters; the
    highest-``scores`` member of each cluster is its representative.
    """
    corr = np.asarray(corr_denoised, dtype=float)
    if corr.ndim != 2 or corr.shape[0] != corr.shape[1]:
        raise ValueError(f"corr_denoised must be square, got shape {corr.shape}")
    n = corr.shape[0]
    sc = np.asarray(scores, dtype=float).ravel()
    if sc.shape != (n,):
        raise ValueError(f"scores has shape {sc.shape}, expected ({n},)")
    if k < 1:
        raise ValueError(f"k must be >= 1, got {k}")
    if not np.isfinite(corr).all():
        raise ValueError("corr_denoised contains NaN/inf")

    k_eff = min(k, n)
    if k_eff >= n:
        # Every asset is its own cluster — keep them all.
        selected: list[int] = list(range(n))
        return SelectionResult(
            selected=selected,
            cluster_of={i: i for i in selected},
            score_of={i: float(sc[i]) for i in selected},
        )

    # Distance 1 − ρ, clamped to [0, 2], zero diagonal for squareform.
    dist = 1.0 - corr
    dist = np.clip((dist + dist.T) / 2.0, 0.0, 2.0)
    np.fill_diagonal(dist, 0.0)
    condensed = squareform(dist, checks=False)
    z = linkage(condensed, method="average")
    labels = fcluster(z, t=k_eff, criterion="maxclust")

    selected: list[int] = []
    cluster_of: dict[int, int] = {}
    score_of: dict[int, float] = {}
    for cluster_id in np.unique(labels):
        members = np.where(labels == cluster_id)[0]
        # Highest quality within the cluster; ties broken by lowest index.
        rep = int(members[np.argmax(sc[members])])
        selected.append(rep)
        cluster_of[rep] = int(cluster_id)
        score_of[rep] = float(sc[rep])
    selected.sort()
    return SelectionResult(
        selected=selected, cluster_of=cluster_of, score_of=score_of
    )
