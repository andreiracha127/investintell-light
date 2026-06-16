"""Unit tests for app.optimizer.selection — Stage-1 robust covariance helper
and the diversification+quality selector.
"""

import numpy as np
import pytest

from app.optimizer import selection


def _planted_clusters(
    t: int = 600, per_cluster: int = 4, n_clusters: int = 3, seed: int = 0
) -> np.ndarray:
    """(T, N) returns with ``n_clusters`` blocks; each block shares a factor."""
    rng = np.random.default_rng(seed)
    cols = []
    for c in range(n_clusters):
        common = rng.standard_normal((t, 1))
        for _ in range(per_cluster):
            idio = rng.standard_normal((t, 1))
            cols.append(0.85 * common + 0.15 * idio)
    return np.hstack(cols)


# ── robust_selection_covariance ──────────────────────────────────────────────


def test_robust_selection_covariance_returns_psd_unit_diag_corr() -> None:
    x = _planted_clusters(seed=1)
    corr, kept, excluded = selection.robust_selection_covariance(
        x, min_pair_overlap=252
    )
    n = len(kept)
    assert corr.shape == (n, n)
    np.testing.assert_allclose(np.diag(corr), np.ones(n), atol=1e-8)
    np.testing.assert_allclose(corr, corr.T, atol=1e-10)
    assert np.linalg.eigvalsh(corr).min() > -1e-9  # PSD after repair
    assert excluded == {}


def test_robust_selection_covariance_excludes_short_history() -> None:
    x = _planted_clusters(seed=2)
    x[80:, 5] = np.nan  # one column with only 80 obs
    corr, kept, excluded = selection.robust_selection_covariance(
        x, min_pair_overlap=252
    )
    assert 5 not in kept
    assert 5 in excluded
    assert corr.shape == (len(kept), len(kept))
