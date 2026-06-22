import numpy as np
import pandas as pd

from app.analytics import aligned
from app.optimizer.engine import sigma_ledoit_wolf


def test_asset_set_key_is_order_invariant_and_window_sensitive():
    k1 = aligned.asset_set_key(["AAPL", "MSFT"], 252)
    k2 = aligned.asset_set_key(["MSFT", "AAPL"], 252)
    k3 = aligned.asset_set_key(["AAPL", "MSFT"], 126)
    assert k1 == k2          # order-invariant
    assert k1 != k3          # window changes the key
    assert len(k1) == 64     # sha256 hex


def test_lw_cov_matches_engine_sigma_ledoit_wolf():
    rng = np.random.default_rng(0)
    returns = rng.normal(0, 0.01, size=(300, 4))
    expected = sigma_ledoit_wolf(returns)
    got = aligned.ledoit_wolf_cov_cached(returns)
    assert np.allclose(got, expected, atol=1e-12)


def test_lw_cov_cache_returns_same_object_for_same_key():
    aligned.clear_lw_cache()
    rng = np.random.default_rng(1)
    returns = rng.normal(0, 0.01, size=(300, 3))
    key = aligned.asset_set_key(["A", "B", "C"], 252)
    first = aligned.ledoit_wolf_cov_cached(returns, cache_key=key)
    # A second call with the SAME key must not recompute — returns cached array.
    second = aligned.ledoit_wolf_cov_cached(
        np.zeros_like(returns), cache_key=key  # different data, same key
    )
    assert second is first


def test_align_return_matrix_inner_joins_on_common_dates():
    idx_a = pd.to_datetime(["2026-06-15", "2026-06-16", "2026-06-17"])
    idx_b = pd.to_datetime(["2026-06-16", "2026-06-17", "2026-06-18"])
    a = pd.Series([0.01, 0.02, 0.03], index=idx_a, name="A")
    b = pd.Series([0.04, 0.05, 0.06], index=idx_b, name="B")
    frame = aligned.align_return_matrix({"A": a, "B": b})
    assert list(frame.columns) == ["A", "B"]
    assert len(frame) == 2  # only 06-16 and 06-17 are common
