import numpy as np
import pandas as pd

from app.analytics.return_convention import GLITCH_LOG_THRESHOLD, to_simple_returns


def test_log_clean_converts_with_expm1():
    out = to_simple_returns(np.array([0.01, -0.02, 0.0]))
    np.testing.assert_allclose(out, np.expm1([0.01, -0.02, 0.0]))


def test_glitch_logs_are_zeroed_then_expm1():
    # PAAA-style round-trip pair: both |log| > 0.40 -> zeroed -> expm1(0) == 0
    out = to_simple_returns(np.array([-6.89060912, 6.891625897]))
    np.testing.assert_allclose(out, [0.0, 0.0], atol=1e-12)


def test_threshold_boundary_keeps_just_below_and_zeros_just_above():
    out = to_simple_returns(np.array([0.40, 0.4001]))
    # 0.40 is NOT > 0.40 -> kept (expm1); 0.4001 > 0.40 -> zeroed
    np.testing.assert_allclose(out, [np.expm1(0.40), 0.0])


def test_arithmetic_is_identity_even_when_large():
    out = to_simple_returns(np.array([0.01, 0.9]), ["arithmetic", "arithmetic"])
    np.testing.assert_allclose(out, [0.01, 0.9])


def test_mixed_conventions_per_element():
    out = to_simple_returns(np.array([0.01, 0.01]), ["log", "arithmetic"])
    np.testing.assert_allclose(out, [np.expm1(0.01), 0.01])


def test_series_preserves_index():
    s = pd.Series([0.01, -0.02], index=pd.to_datetime(["2020-01-02", "2020-01-03"]))
    out = to_simple_returns(s)
    assert isinstance(out, pd.Series)
    assert list(out.index) == list(s.index)


def test_nan_propagates_positionally():
    out = to_simple_returns(np.array([np.nan, 0.01]))
    assert np.isnan(out[0])
    np.testing.assert_allclose(out[1], np.expm1(0.01))


def test_threshold_constant_matches_harness():
    assert GLITCH_LOG_THRESHOLD == 0.40
