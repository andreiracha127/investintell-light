"""CVaR annualization + realized-CVaR verifier (rank 39)."""

import math

import numpy as np
import pandas as pd
import pytest

from app.analytics import risk


def _series(values: list[float]) -> pd.Series:
    idx = pd.date_range("2020-01-01", periods=len(values), freq="B")
    return pd.Series(values, index=idx, dtype=float)


def test_annualize_cvar_sqrt_time_scaling() -> None:
    # Square-root-of-time: annual = periodic * sqrt(periods_per_year).
    periodic_cvar = 0.02
    annual = risk.annualize_cvar(periodic_cvar, periods_per_year=252)
    assert math.isclose(annual, 0.02 * math.sqrt(252), rel_tol=1e-12)


def test_annualize_cvar_monthly() -> None:
    annual = risk.annualize_cvar(0.05, periods_per_year=12)
    assert math.isclose(annual, 0.05 * math.sqrt(12), rel_tol=1e-12)


def test_annualize_cvar_rejects_negative_input() -> None:
    # CVaR in this module is a POSITIVE loss magnitude (risk.historical_cvar).
    with pytest.raises(ValueError, match="positive"):
        risk.annualize_cvar(-0.02)


def test_annualize_cvar_rejects_bad_periods() -> None:
    with pytest.raises(ValueError, match="periods_per_year"):
        risk.annualize_cvar(0.02, periods_per_year=0)


def test_verify_realized_cvar_within_limit() -> None:
    # Mild returns: realized CVaR well below a generous 10% limit.
    rng = np.random.default_rng(7)
    returns = _series(list(rng.normal(0.0, 0.01, 300)))
    result = risk.verify_realized_cvar(returns, cvar_limit=0.10, confidence=0.95)
    assert result.realized_cvar > 0.0
    assert result.realized_cvar < 0.10
    assert result.breach is False
    assert 0.0 <= result.utilization < 1.0


def test_verify_realized_cvar_breach() -> None:
    # Fat left tail forces realized CVaR above a tight 1% limit.
    base = [0.001] * 282
    crash = [-0.20] * 18  # >5% of 300 so the 95% tail genuinely captures the crash
    returns = _series(base + crash)
    result = risk.verify_realized_cvar(returns, cvar_limit=0.01, confidence=0.95)
    assert result.realized_cvar > 0.01
    assert result.breach is True
    assert result.utilization > 1.0


def test_verify_realized_cvar_rejects_nonpositive_limit() -> None:
    returns = _series([0.001] * 50)
    with pytest.raises(ValueError, match="cvar_limit"):
        risk.verify_realized_cvar(returns, cvar_limit=0.0)


def test_verify_realized_cvar_rejects_short_window() -> None:
    returns = _series([0.001] * 5)
    with pytest.raises(ValueError, match="at least 10"):
        risk.verify_realized_cvar(returns, cvar_limit=0.05)
