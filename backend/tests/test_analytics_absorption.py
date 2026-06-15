"""Unit tests for app/analytics/absorption.py (Kritzman–Li absorption ratio).

Pure function over a symmetric correlation matrix — no DB, no I/O. The matrix
is the kind app/analytics/portfolio.py::correlation_matrix produces. Mirrors the
legacy semantics in correlation_regime_service.py::_compute_concentration but
with no shrinkage / denoising machinery.
"""

import numpy as np
import pytest

from app.analytics.absorption import AbsorptionResult, absorption_ratio


def _identity_corr(n: int) -> np.ndarray:
    """Perfectly diversified: identity → every eigenvalue == 1."""
    return np.eye(n, dtype=float)


def _equicorrelated(n: int, rho: float) -> np.ndarray:
    """Constant off-diagonal correlation rho; eigenvalues are
    {1 + (n-1)rho} (once) and {1 - rho} (n-1 times)."""
    m = np.full((n, n), rho, dtype=float)
    np.fill_diagonal(m, 1.0)
    return m


def test_identity_matrix_is_maximally_diversified() -> None:
    # n=10, k = max(1, 10//5) = 2 top eigenvalues over total 10 → 0.2
    result = absorption_ratio(_identity_corr(10))
    assert isinstance(result, AbsorptionResult)
    assert result.n_assets == 10
    assert result.top_k == 2
    assert result.absorption_ratio == pytest.approx(0.2, abs=1e-9)
    assert result.first_eigenvalue_ratio == pytest.approx(0.1, abs=1e-9)
    assert result.absorption_status == "normal"
    assert result.concentration_status == "diversified"
    # eigenvalues are returned sorted descending, summing to the trace (== n)
    assert result.eigenvalues[0] >= result.eigenvalues[-1]
    assert sum(result.eigenvalues) == pytest.approx(10.0, abs=1e-9)


def test_equicorrelated_high_rho_is_concentrated_and_critical() -> None:
    # rho=0.9, n=10: lambda_1 = 1 + 9*0.9 = 9.1; total = 10.
    # first_eigenvalue_ratio = 0.91 (> 0.80 → high_concentration).
    # k=2: top-2 = 9.1 + (1-0.9) = 9.2 → absorption 0.92 (> 0.90 → critical).
    result = absorption_ratio(_equicorrelated(10, 0.9))
    assert result.first_eigenvalue_ratio == pytest.approx(0.91, abs=1e-9)
    assert result.concentration_status == "high_concentration"
    assert result.absorption_ratio == pytest.approx(0.92, abs=1e-9)
    assert result.absorption_status == "critical"


def test_moderate_band_is_strict_greater_than() -> None:
    # Construct a 2x2 corr with lambda_1/total exactly 0.60 → "diversified"
    # (strict >). 2x2 corr [[1, r],[r, 1]] has eigenvalues 1+r, 1-r; total 2.
    # first ratio = (1+r)/2 = 0.60 → r = 0.20.
    result = absorption_ratio(_equicorrelated(2, 0.20))
    assert result.first_eigenvalue_ratio == pytest.approx(0.60, abs=1e-9)
    assert result.concentration_status == "diversified"  # 0.60 NOT > 0.60
    # Nudge above the band: r=0.21 → first ratio 0.605 → moderate.
    result2 = absorption_ratio(_equicorrelated(2, 0.21))
    assert result2.first_eigenvalue_ratio == pytest.approx(0.605, abs=1e-9)
    assert result2.concentration_status == "moderate_concentration"


def test_custom_top_k_overrides_default() -> None:
    result = absorption_ratio(_identity_corr(20), top_k=1)
    assert result.top_k == 1
    assert result.absorption_ratio == pytest.approx(0.05, abs=1e-9)  # 1/20


def test_accepts_dataframe_to_numpy() -> None:
    # The optimizer's correlation_matrix returns a DataFrame; .to_numpy() of it
    # must work the same as a raw array.
    pd = pytest.importorskip("pandas")
    frame = pd.DataFrame(_identity_corr(10))
    result = absorption_ratio(frame.to_numpy(dtype=float))
    assert result.absorption_ratio == pytest.approx(0.2, abs=1e-9)


def test_rejects_non_square_matrix() -> None:
    with pytest.raises(ValueError, match="square"):
        absorption_ratio(np.ones((3, 4), dtype=float))


def test_rejects_nan_or_inf() -> None:
    bad = _identity_corr(3)
    bad[0, 1] = bad[1, 0] = np.nan
    with pytest.raises(ValueError, match="NaN or infinite"):
        absorption_ratio(bad)


def test_rejects_asymmetric_matrix() -> None:
    bad = np.array([[1.0, 0.5], [0.2, 1.0]], dtype=float)
    with pytest.raises(ValueError, match="symmetric"):
        absorption_ratio(bad)


def test_rejects_too_few_assets() -> None:
    with pytest.raises(ValueError, match="at least 2"):
        absorption_ratio(np.array([[1.0]], dtype=float))


def test_rejects_degenerate_zero_trace() -> None:
    with pytest.raises(ValueError, match="non-positive total variance"):
        absorption_ratio(np.zeros((3, 3), dtype=float))


def test_top_k_out_of_range_is_loud() -> None:
    with pytest.raises(ValueError, match="top_k"):
        absorption_ratio(_identity_corr(5), top_k=6)
    with pytest.raises(ValueError, match="top_k"):
        absorption_ratio(_identity_corr(5), top_k=0)
