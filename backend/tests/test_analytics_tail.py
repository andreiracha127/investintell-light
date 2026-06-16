"""Tests for app.analytics.tail — Cornish-Fisher tail-VaR panel."""

import numpy as np
import pandas as pd
import pytest
from scipy.stats import t as student_t

from app.analytics.tail import TailPanel, tail_panel


def _dated(values: list[float], start: str = "2020-01-01") -> pd.Series:
    return pd.Series(values, index=pd.date_range(start, periods=len(values), freq="B"))


def _normal_returns(n: int = 250, seed: int = 7) -> pd.Series:
    rng = np.random.default_rng(seed)
    return _dated(list(rng.normal(0.0003, 0.012, n)))


def _fat_tailed_returns(n: int = 600, seed: int = 42) -> pd.Series:
    rng = np.random.default_rng(seed)
    return _dated(list(student_t.rvs(3, size=n, random_state=rng) * 0.01))


# --- shape / sign convention --------------------------------------------------


def test_tail_panel_returns_positive_loss_var() -> None:
    """Parametric VaR is a POSITIVE loss magnitude under our convention."""
    panel = tail_panel(_normal_returns())
    assert panel.var_parametric_95 > 0
    assert panel.var_parametric_99 > 0
    assert panel.var_parametric_99 >= panel.var_parametric_95


def test_tail_panel_modified_var_positive_and_monotonic_on_normal_data() -> None:
    panel = tail_panel(_normal_returns())
    assert panel.var_modified_95 > 0
    assert panel.var_modified_99 >= panel.var_modified_95


# --- the Cornish-Fisher monotonicity clamp ------------------------------------


def test_cornish_fisher_clamp_fires_on_right_skewed_sample() -> None:
    """A strongly right-skewed sample makes the RAW CF expansion non-monotonic
    in confidence: the raw 99% positive-loss falls BELOW the raw 95% loss, which
    would report the deeper tail as less severe. The clamp must force
    mVaR99 >= mVaR95 (the more-severe positive loss wins).

    Verified numerically on this exact sample (exponential minus its mean,
    seed 11, n=300): empirical skew=1.54, excess-kurt=2.02, raw mVaR95=0.01139,
    raw mVaR99=0.00788 -> clamp fires -> post mVaR99 = mVaR95 = 0.01139.
    """
    rng = np.random.default_rng(11)
    base = rng.exponential(0.01, 300) - 0.01  # right-skewed (skew > 0)
    panel = tail_panel(_dated(list(base)))
    assert panel.var_modified_99 >= panel.var_modified_95


def test_cornish_fisher_clamp_fires_on_leptokurtic_spike_cluster() -> None:
    """A cluster of large positive outliers drives skew/kurtosis high enough
    that the raw CF 99% quantile crosses to the wrong side. The post-clamp
    invariant must hold.

    Verified numerically on this exact sample (seed 5, n=300): empirical
    skew=3.27, excess-kurt=10.13, raw mVaR95=0.00118, raw mVaR99=-0.03556 ->
    clamp fires -> post mVaR99 = mVaR95.
    """
    rng = np.random.default_rng(5)
    spikes = np.concatenate([
        rng.normal(0.0, 0.005, 280),
        rng.uniform(0.05, 0.09, 20),  # a cluster of large positive outliers
    ])
    panel = tail_panel(_dated(list(spikes)))
    assert panel.var_modified_99 >= panel.var_modified_95


# --- Jarque-Bera --------------------------------------------------------------


def test_jarque_bera_accepts_normal_data() -> None:
    panel = tail_panel(_normal_returns(500, seed=3))
    assert panel.jarque_bera_pvalue > 0.05
    assert panel.is_normal is True


def test_jarque_bera_rejects_fat_tailed_data() -> None:
    panel = tail_panel(_fat_tailed_returns())
    assert panel.jarque_bera_pvalue < 0.05
    assert panel.is_normal is False
    assert panel.jarque_bera_stat > 0


# --- ETR / Rachev (right tail, full panel only) -------------------------------


def test_etr_and_rachev_present_for_full_panel() -> None:
    panel = tail_panel(_fat_tailed_returns())
    # ETR is a positive expected-gain magnitude (mean of the right tail).
    assert panel.etr_95 is not None
    assert panel.etr_95 > 0
    # ETL is a positive expected-loss magnitude.
    assert panel.etl_95 is not None
    assert panel.etl_95 > 0
    # Rachev = ETR / ETL is a positive ratio when both tails are well-defined.
    assert panel.rachev_ratio is not None
    assert panel.rachev_ratio > 0


# --- tiered n gates -----------------------------------------------------------


def test_short_sample_raises() -> None:
    with pytest.raises(ValueError, match="at least 30"):
        tail_panel(_normal_returns(29))


def test_medium_sample_has_parametric_and_jb_but_no_historical_tail() -> None:
    """30 <= n < 100: parametric VaR + Jarque-Bera, but ETL/ETR/Rachev are None."""
    panel = tail_panel(_normal_returns(60, seed=2))
    assert panel.var_parametric_95 > 0
    assert panel.var_modified_95 > 0
    assert panel.jarque_bera_stat > 0
    assert panel.etl_95 is None
    assert panel.etr_95 is None
    assert panel.rachev_ratio is None


def test_nan_input_raises() -> None:
    bad = _normal_returns(120)
    bad.iloc[10] = float("nan")
    with pytest.raises(ValueError, match="NaN"):
        tail_panel(bad)


def test_zero_variance_raises() -> None:
    with pytest.raises(ValueError, match="variance"):
        tail_panel(_dated([0.01] * 120))


def test_tail_panel_is_frozen_dataclass() -> None:
    panel = tail_panel(_normal_returns())
    assert isinstance(panel, TailPanel)
    with pytest.raises((AttributeError, TypeError)):
        panel.var_parametric_95 = 0.0  # type: ignore[misc]
