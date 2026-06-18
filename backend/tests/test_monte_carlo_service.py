"""Tests for the Monte Carlo schema and service."""

import datetime as dt
import uuid
from typing import Any

import numpy as np
import pandas as pd
import pytest
from pydantic import ValidationError

from app.optimizer import data as optimizer_data
from app.schemas.monte_carlo import (
    MAX_SIMULATIONS,
    MIN_SIMULATIONS,
    MonteCarloRequest,
    PortfolioMonteCarloRequest,
    PortfolioMonteCarloResponse,
)
from app.services.monte_carlo import assemble_monte_carlo
from app.services.monte_carlo import (
    assemble_portfolio_monte_carlo,
    run_portfolio_monte_carlo,
)
from app.services.stock_analysis import InsufficientDataError


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


_PMC_FUND_IDS = [
    uuid.UUID(f"00000000-0000-0000-0000-00000000000{i}") for i in range(1, 4)
]


def _pmc_fund(i: int) -> dict[str, str]:
    return {"kind": "fund", "id": str(_PMC_FUND_IDS[i])}


def _aligned_frame(n_obs: int = 500, seed: int = 21) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    index = pd.bdate_range("2018-01-02", periods=n_obs)
    labels = [f"fund:{_PMC_FUND_IDS[i]}" for i in range(2)]
    return pd.DataFrame(
        {
            lbl: rng.normal(0.0004, 0.009 + 0.001 * i, n_obs)
            for i, lbl in enumerate(labels)
        },
        index=index,
    )


def test_assemble_portfolio_uses_frame_at_w_synthetic_series() -> None:
    # The portfolio series fed to the bootstrap must equal frame @ w exactly:
    # we verify by comparing the historical_value to the statistic recomputed on
    # frame @ w via the pure analytics layer (same numbers, no I/O).
    from app.analytics.monte_carlo import block_bootstrap_monte_carlo

    frame = _aligned_frame()
    w = np.array([0.7, 0.3])
    series = frame.to_numpy() @ w
    expected = block_bootstrap_monte_carlo(
        series,
        n_simulations=2000,
        statistic="return",
        seed=3,
    )
    resp = assemble_portfolio_monte_carlo(
        series,
        statistic="return",
        n_assets=2,
        n_simulations=2000,
        horizons=None,
        risk_free_rate=0.04,
        seed=3,
    )
    assert resp.params.n_assets == 2
    assert resp.historical_value == expected.historical_value
    assert resp.percentiles == expected.percentiles


def test_assemble_short_history_maps_to_insufficient_data() -> None:
    short = np.random.default_rng(0).normal(0.0004, 0.01, 40)
    with pytest.raises(InsufficientDataError, match="insufficient_history"):
        assemble_portfolio_monte_carlo(
            short,
            statistic="max_drawdown",
            n_assets=2,
            n_simulations=1000,
            horizons=None,
            risk_free_rate=0.04,
            seed=1,
        )


async def test_run_builds_weight_vector_aligned_to_frame_columns(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    frame = _aligned_frame()

    async def fake_load(
        session: Any,
        assets: Any,
        window_days: int | None = None,
        today: dt.date | None = None,
    ) -> pd.DataFrame:
        # Return columns in a different order than positions to prove alignment.
        return frame[list(reversed(frame.columns))]

    monkeypatch.setattr(optimizer_data, "load_aligned_returns", fake_load)
    payload = PortfolioMonteCarloRequest.model_validate(
        {
            "positions": [
                {"asset": _pmc_fund(0), "weight": 0.7},
                {"asset": _pmc_fund(1), "weight": 0.3},
            ],
            "statistic": "return",
            "n_simulations": 2000,
            "seed": 3,
        }
    )
    resp = await run_portfolio_monte_carlo(None, payload)
    assert isinstance(resp, PortfolioMonteCarloResponse)
    assert resp.params.n_assets == 2
    # Same as the hand-built synthetic series (alignment by label, not order).
    series = frame.to_numpy() @ np.array([0.7, 0.3])
    from app.analytics.monte_carlo import block_bootstrap_monte_carlo

    expected = block_bootstrap_monte_carlo(
        series, n_simulations=2000, statistic="return", seed=3
    )
    assert resp.percentiles == expected.percentiles


async def test_run_insufficient_common_history_maps_to_422(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fake_load(session: Any, assets: Any, **kwargs: Any) -> pd.DataFrame:
        raise ValueError("insufficient common history: 120 overlapping observations")

    monkeypatch.setattr(optimizer_data, "load_aligned_returns", fake_load)
    payload = PortfolioMonteCarloRequest.model_validate(
        {
            "positions": [
                {"asset": _pmc_fund(0), "weight": 0.5},
                {"asset": _pmc_fund(1), "weight": 0.5},
            ]
        }
    )
    with pytest.raises(InsufficientDataError, match="insufficient common history"):
        await run_portfolio_monte_carlo(None, payload)
