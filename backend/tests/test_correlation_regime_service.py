"""Unit tests for the correlation-regime/contagion pure assembler.

assemble_correlation_regime operates on a synthetic (T,N) returns matrix — no
DB, no I/O. Math is delegated to app.analytics.rmt (shared) — these tests pin
the regime/contagion ASSEMBLY, not the RMT primitives (covered in T3F-1).
"""

import numpy as np
import pytest

from app.services import correlation_regime as cr


def _regime_returns(
    t: int, n: int, recent_load: float, base_load: float, window: int = 60, seed: int = 7
) -> np.ndarray:
    """(T,N) returns where the LAST `window` rows have a different common-factor
    loading than the earlier (baseline) rows — a synthetic regime shift."""
    rng = np.random.default_rng(seed)
    base_t = t - window
    base_common = rng.standard_normal((base_t, 1))
    base = base_load * base_common + (1.0 - base_load) * rng.standard_normal((base_t, n))
    rec_common = rng.standard_normal((window, 1))
    rec = recent_load * rec_common + (1.0 - recent_load) * rng.standard_normal((window, n))
    return np.vstack([base, rec])


def test_assemble_returns_full_payload_shape() -> None:
    x = _regime_returns(560, 5, recent_load=0.6, base_load=0.6)
    labels = [f"fund:{i}" for i in range(5)]
    out = cr.assemble_correlation_regime(x, labels)
    assert out.instrument_count == 5
    assert out.labels == labels
    assert len(out.correlation_matrix) == 5
    assert all(len(row) == 5 for row in out.correlation_matrix)
    assert len(out.pair_correlations) == 10  # N*(N-1)/2 unordered pairs
    assert out.concentration.absorption_status in {"normal", "warning", "critical"}
    assert out.sufficient_data is True


def test_assemble_detects_contagion_when_recent_corr_spikes() -> None:
    # Baseline weakly correlated, recent strongly correlated ⇒ contagion pairs.
    x = _regime_returns(560, 4, recent_load=0.95, base_load=0.1)
    labels = [f"fund:{i}" for i in range(4)]
    out = cr.assemble_correlation_regime(x, labels)
    assert any(p.is_contagion for p in out.pair_correlations)
    assert out.regime_shift_detected is True


def test_assemble_no_contagion_in_stable_regime() -> None:
    x = _regime_returns(560, 4, recent_load=0.3, base_load=0.3)
    labels = [f"fund:{i}" for i in range(4)]
    out = cr.assemble_correlation_regime(x, labels)
    assert not any(p.is_contagion for p in out.pair_correlations)


def test_assemble_high_concentration_for_single_factor() -> None:
    x = _regime_returns(560, 6, recent_load=0.97, base_load=0.97)
    labels = [f"fund:{i}" for i in range(6)]
    out = cr.assemble_correlation_regime(x, labels)
    assert out.concentration.first_eigenvalue_ratio > 0.5
    assert out.concentration.concentration_status in {
        "moderate_concentration",
        "high_concentration",
    }


def test_assemble_insufficient_data_flag() -> None:
    x = _regime_returns(40, 3, recent_load=0.5, base_load=0.5, window=20)
    labels = [f"fund:{i}" for i in range(3)]
    out = cr.assemble_correlation_regime(x, labels, min_observations=45)
    assert out.sufficient_data is False
    assert out.pair_correlations == []


def test_assemble_rejects_label_count_mismatch() -> None:
    x = _regime_returns(560, 4, recent_load=0.5, base_load=0.5)
    with pytest.raises(ValueError, match="labels"):
        cr.assemble_correlation_regime(x, ["a", "b"])  # 2 labels, 4 columns


def test_assemble_rejects_nan() -> None:
    x = _regime_returns(560, 3, recent_load=0.5, base_load=0.5)
    x[10, 0] = np.nan
    with pytest.raises(ValueError, match="NaN"):
        cr.assemble_correlation_regime(x, ["a", "b", "c"])


def test_diversification_ratio_at_least_one() -> None:
    x = _regime_returns(560, 5, recent_load=0.6, base_load=0.6)
    labels = [f"fund:{i}" for i in range(5)]
    out = cr.assemble_correlation_regime(x, labels)
    assert out.diversification_ratio >= 1.0 - 1e-9
