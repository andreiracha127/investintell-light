"""Tests for parametric & EVT POT-GPD tail risk in app.analytics.risk."""

import math

import numpy as np
import pandas as pd
import pytest
from scipy.stats import t as student_t

from app.analytics.risk import (
    EvtTailResult,
    evt_tail_var_cvar,
    parametric_cvar,
    parametric_var,
)


def _dated(values: list[float], start: str = "2020-01-01") -> pd.Series:
    return pd.Series(values, index=pd.date_range(start, periods=len(values), freq="B"))


def _normal_returns(n: int = 250, seed: int = 7) -> pd.Series:
    rng = np.random.default_rng(seed)
    return _dated(list(rng.normal(0.0003, 0.012, n)))


def _fat_tailed_returns(n: int = 600, seed: int = 42) -> pd.Series:
    rng = np.random.default_rng(seed)
    return _dated(list(student_t.rvs(3, size=n, random_state=rng) * 0.01))


# --- parametric Gaussian VaR / CVaR -------------------------------------------


def test_parametric_var_positive_and_monotonic() -> None:
    r = _normal_returns()
    assert parametric_var(r, 0.95) > 0
    assert parametric_var(r, 0.99) >= parametric_var(r, 0.95)


def test_parametric_cvar_at_least_var() -> None:
    r = _normal_returns()
    assert parametric_cvar(r, 0.95) >= parametric_var(r, 0.95)


def test_parametric_cvar_monotonic() -> None:
    r = _normal_returns(500, seed=17)
    assert parametric_cvar(r, 0.99) >= parametric_cvar(r, 0.95)


def test_parametric_bad_confidence_raises() -> None:
    with pytest.raises(ValueError, match="confidence"):
        parametric_var(_normal_returns(), confidence=95.0)


def test_parametric_short_input_raises() -> None:
    with pytest.raises(ValueError, match="at least 10"):
        parametric_var(_dated([0.01] * 9))


def test_parametric_zero_variance_raises() -> None:
    with pytest.raises(ValueError, match="variance"):
        parametric_cvar(_dated([0.01] * 30))


def test_parametric_nan_raises() -> None:
    bad = _normal_returns(50)
    bad.iloc[3] = float("nan")
    with pytest.raises(ValueError, match="NaN"):
        parametric_var(bad)


# --- EVT POT-GPD carrier ------------------------------------------------------


def test_evt_tail_on_fat_tailed_data_is_well_defined() -> None:
    res = evt_tail_var_cvar(_fat_tailed_returns(), confidence=0.99)
    assert isinstance(res, EvtTailResult)
    assert res.degraded is False
    assert res.degraded_reason is None
    assert res.var > 0
    assert res.cvar >= res.var
    assert res.evt_n_exceedances >= 20
    assert res.evt_threshold > 0
    assert math.isfinite(res.evt_xi)


def test_evt_cvar_exceeds_parametric_on_fat_tails() -> None:
    """On genuinely fat-tailed (Student-t df=3) data, the EVT CVaR at 99% is
    materially larger than the Gaussian parametric CVaR — the whole point of
    using EVT for the deep tail. (Verified: EVT CVaR99 ~0.0808 vs parametric
    CVaR99 ~0.0480.)
    """
    r = _fat_tailed_returns()
    evt = evt_tail_var_cvar(r, confidence=0.99)
    assert evt.degraded is False
    assert evt.cvar > parametric_cvar(r, 0.99)


def test_evt_degrades_fail_closed_on_insufficient_losses() -> None:
    """An all-positive series has zero losses, so a GPD tail cannot be fit: the
    carrier must report degraded with NaN values and a reason — NEVER a silent
    0.0 (fail-closed). (Verified: 200 |gains| -> 0 losses -> insufficient_losses.)
    """
    rng = np.random.default_rng(1)
    almost_all_gains = _dated(list(np.abs(rng.normal(0.01, 0.002, 200))))
    res = evt_tail_var_cvar(almost_all_gains, confidence=0.99)
    assert res.degraded is True
    assert res.degraded_reason == "insufficient_losses"
    assert math.isnan(res.var)
    assert math.isnan(res.cvar)


def test_evt_degrades_fail_closed_on_short_sample() -> None:
    res = evt_tail_var_cvar(_normal_returns(50), confidence=0.99)
    assert res.degraded is True
    assert res.degraded_reason == "insufficient_obs"
    assert math.isnan(res.var)
    assert math.isnan(res.cvar)


def test_evt_nan_input_raises() -> None:
    """NaN is a caller bug, not a degradable tail condition — fail loud."""
    bad = _fat_tailed_returns()
    bad.iloc[5] = float("nan")
    with pytest.raises(ValueError, match="NaN"):
        evt_tail_var_cvar(bad, confidence=0.99)


def test_evt_bad_confidence_raises() -> None:
    with pytest.raises(ValueError, match="confidence"):
        evt_tail_var_cvar(_fat_tailed_returns(), confidence=1.5)


def test_evt_result_is_frozen() -> None:
    res = evt_tail_var_cvar(_fat_tailed_returns(), confidence=0.99)
    with pytest.raises((AttributeError, TypeError)):
        res.degraded = True  # type: ignore[misc]
