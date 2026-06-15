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
