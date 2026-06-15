"""Tests for the Monte Carlo schema and service."""

import pytest
from pydantic import ValidationError

from app.schemas.monte_carlo import (
    MAX_SIMULATIONS,
    MIN_SIMULATIONS,
    MonteCarloRequest,
)


def test_request_defaults() -> None:
    req = MonteCarloRequest(ticker="aapl")
    assert req.ticker == "AAPL"  # normalized to uppercase
    assert req.statistic == "max_drawdown"
    assert req.range == "MAX"
    assert req.n_simulations == 10_000
    assert req.horizons is None
    assert req.risk_free_rate == pytest.approx(0.04)
    assert req.seed is None


def test_request_rejects_low_simulations() -> None:
    with pytest.raises(ValidationError):
        MonteCarloRequest(ticker="AAPL", n_simulations=MIN_SIMULATIONS - 1)


def test_request_rejects_high_simulations() -> None:
    with pytest.raises(ValidationError):
        MonteCarloRequest(ticker="AAPL", n_simulations=MAX_SIMULATIONS + 1)


def test_request_rejects_unknown_statistic() -> None:
    with pytest.raises(ValidationError):
        MonteCarloRequest(ticker="AAPL", statistic="median")


def test_request_rejects_nonpositive_horizon() -> None:
    with pytest.raises(ValidationError, match="horizons must all be >= 1"):
        MonteCarloRequest(ticker="AAPL", horizons=[252, 0])


def test_request_rejects_empty_horizons() -> None:
    with pytest.raises(ValidationError, match="horizons must be non-empty"):
        MonteCarloRequest(ticker="AAPL", horizons=[])


import numpy as np

from app.services.monte_carlo import assemble_monte_carlo
from app.services.stock_analysis import InsufficientDataError


def _mc_returns(n: int = 500, seed: int = 13) -> np.ndarray:
    rng = np.random.default_rng(seed)
    return rng.normal(0.0004, 0.01, n)


def test_assemble_returns_response_shape() -> None:
    resp = assemble_monte_carlo(
        _mc_returns(),
        ticker="AAPL",
        statistic="max_drawdown",
        range_key="MAX",
        n_simulations=2000,
        horizons=None,
        risk_free_rate=0.04,
        seed=42,
    )
    assert resp.params.ticker == "AAPL"
    assert resp.params.statistic == "max_drawdown"
    assert resp.params.n_simulations == 2000
    assert resp.params.seed == 42
    assert set(resp.percentiles.keys()) == {
        "1st", "5th", "10th", "25th", "50th", "75th", "90th", "95th", "99th"
    }
    assert resp.historical_percentile_rank is not None
    assert resp.confidence_bars[0].horizon == "1Y"
    assert resp.confidence_bars[0].horizon_days == 252
    assert resp.degraded is False


def test_assemble_is_deterministic_under_seed() -> None:
    r = _mc_returns()
    kwargs = dict(
        ticker="AAPL", statistic="return", range_key="MAX",
        n_simulations=1500, horizons=None, risk_free_rate=0.04, seed=99,
    )
    a = assemble_monte_carlo(r, **kwargs)
    b = assemble_monte_carlo(r, **kwargs)
    assert a.percentiles == b.percentiles
    assert a.median == b.median


def test_assemble_short_history_maps_to_insufficient_data() -> None:
    with pytest.raises(InsufficientDataError, match="insufficient_history"):
        assemble_monte_carlo(
            _mc_returns(n=40),
            ticker="AAPL",
            statistic="max_drawdown",
            range_key="MAX",
            n_simulations=1000,
            horizons=None,
            risk_free_rate=0.04,
            seed=1,
        )


def test_assemble_horizon_guard_maps_to_insufficient_data() -> None:
    with pytest.raises(InsufficientDataError, match="insufficient_history_for_horizon"):
        assemble_monte_carlo(
            _mc_returns(n=60),
            ticker="AAPL",
            statistic="max_drawdown",
            range_key="MAX",
            n_simulations=1000,
            horizons=None,
            risk_free_rate=0.04,
            seed=1,
        )
