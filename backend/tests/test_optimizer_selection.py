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
    for _c in range(n_clusters):
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

# ── quality_score ────────────────────────────────────────────────────────────


def test_quality_score_ranks_high_sharpe_low_expense_high_aum_first() -> None:
    metrics = [
        {"sharpe_1y": 2.0, "expense_ratio": 0.001, "aum_usd": 1e10},  # best
        {"sharpe_1y": 0.1, "expense_ratio": 0.02, "aum_usd": 1e7},  # worst
        {"sharpe_1y": 1.0, "expense_ratio": 0.01, "aum_usd": 1e8},  # mid
    ]
    scores = selection.quality_score(metrics)
    assert scores.shape == (3,)
    assert scores[0] > scores[2] > scores[1]


def test_quality_score_neutral_for_all_missing() -> None:
    metrics = [
        {"sharpe_1y": None, "expense_ratio": None, "aum_usd": None},
        {"sharpe_1y": None, "expense_ratio": None, "aum_usd": None},
    ]
    scores = selection.quality_score(metrics)
    np.testing.assert_allclose(scores, [0.5, 0.5], atol=1e-12)


# ── select_diversified ───────────────────────────────────────────────────────


def test_select_diversified_picks_one_per_cluster() -> None:
    """3 planted clusters of 4 ⇒ asking for K=3 returns exactly one index from
    each cluster block (0-3, 4-7, 8-11)."""
    x = _planted_clusters(per_cluster=4, n_clusters=3, seed=7)
    corr, kept, _ = selection.robust_selection_covariance(x, min_pair_overlap=252)
    scores = np.linspace(0, 1, len(kept))  # arbitrary but distinct
    result = selection.select_diversified(corr, scores, k=3)
    assert len(result.selected) == 3
    blocks = {idx // 4 for idx in result.selected}
    assert blocks == {0, 1, 2}  # one representative per planted cluster
    # Every selected index carries a cluster label and its score.
    assert set(result.cluster_of) == set(result.selected)


def test_select_diversified_picks_best_quality_within_cluster() -> None:
    """Within a cluster, the highest-score member is the representative."""
    x = _planted_clusters(per_cluster=4, n_clusters=2, seed=8)
    corr, kept, _ = selection.robust_selection_covariance(x, min_pair_overlap=252)
    scores = np.zeros(len(kept))
    scores[2] = 1.0  # best in cluster 0 (indices 0-3)
    scores[5] = 1.0  # best in cluster 1 (indices 4-7)
    result = selection.select_diversified(corr, scores, k=2)
    assert set(result.selected) == {2, 5}


def test_select_diversified_caps_k_at_available() -> None:
    x = _planted_clusters(per_cluster=2, n_clusters=2, seed=9)  # 4 assets
    corr, kept, _ = selection.robust_selection_covariance(x, min_pair_overlap=252)
    scores = np.linspace(0, 1, len(kept))
    result = selection.select_diversified(corr, scores, k=99)  # more than N
    assert len(result.selected) == len(kept)  # cannot exceed available


def test_select_diversified_rejects_shape_mismatch() -> None:
    corr = np.eye(4)
    with pytest.raises(ValueError, match="scores"):
        selection.select_diversified(corr, np.zeros(3), k=2)
