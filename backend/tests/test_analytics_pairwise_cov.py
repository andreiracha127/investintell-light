"""Unit tests for app.analytics.pairwise_cov — pairwise covariance over a
returns matrix WITH NaN (no global dropna), vectorized via an availability
mask, with a minimum-overlap guard and fail-loud exclusion.
"""

import numpy as np
import pytest

from app.analytics import pairwise_cov


def _factor_returns(t: int, n: int, load: float = 0.6, seed: int = 0) -> np.ndarray:
    rng = np.random.default_rng(seed)
    common = rng.standard_normal((t, 1))
    idio = rng.standard_normal((t, n))
    return load * common + (1.0 - load) * idio


def test_pairwise_matches_np_cov_when_no_nan() -> None:
    """With a fully-observed matrix, pairwise cov == np.cov (1/n convention)."""
    x = _factor_returns(300, 5, seed=1)
    cov, kept, excluded = pairwise_cov.pairwise_covariance(x, min_pair_overlap=50)
    assert kept == [0, 1, 2, 3, 4]
    assert excluded == {}
    expected = np.cov(x, rowvar=False, bias=True)  # bias=True ⇒ /n convention
    np.testing.assert_allclose(cov, expected, atol=1e-10)


def test_pairwise_handles_known_nan_pattern() -> None:
    """A planted NaN block reduces the pair overlap; the resulting pairwise
    mean/cov match a hand-computed reference on the overlapping rows only."""
    x = _factor_returns(400, 3, seed=2)
    x[:100, 0] = np.nan  # column 0 missing its first 100 rows
    cov, kept, excluded = pairwise_cov.pairwise_covariance(x, min_pair_overlap=252)
    assert kept == [0, 1, 2]
    assert excluded == {}
    # Reference for the (0, 1) entry: overlap is rows 100..399.
    a = x[100:, 0]
    b = x[100:, 1]
    n_ij = a.size
    ref = float((a @ b) / n_ij - (a.mean()) * (b.mean()))
    assert cov[0, 1] == pytest.approx(ref, abs=1e-10)


def test_pairwise_excludes_fund_below_overlap_threshold() -> None:
    """A column whose median pairwise overlap falls below the threshold is
    excluded (structured reason), not silently kept."""
    x = _factor_returns(400, 4, seed=3)
    x[50:, 2] = np.nan  # column 2 has only 50 observations ⇒ tiny overlaps
    cov, kept, excluded = pairwise_cov.pairwise_covariance(x, min_pair_overlap=252)
    assert 2 not in kept
    assert kept == [0, 1, 3]
    assert 2 in excluded
    assert "overlap" in excluded[2].lower()
    assert cov.shape == (3, 3)


def test_pairwise_fails_loud_with_fewer_than_two_viable() -> None:
    x = _factor_returns(400, 3, seed=4)
    x[50:, 1] = np.nan
    x[50:, 2] = np.nan  # only column 0 keeps a long history
    with pytest.raises(ValueError, match="at least 2"):
        pairwise_cov.pairwise_covariance(x, min_pair_overlap=252)


def test_pairwise_rejects_non_2d() -> None:
    with pytest.raises(ValueError, match=r"\(T, N\)"):
        pairwise_cov.pairwise_covariance(np.zeros(5), min_pair_overlap=10)
