"""Schema contract for POST /monte-carlo/portfolio."""

import uuid

import pytest
from pydantic import ValidationError

from app.schemas.monte_carlo import (
    PortfolioMonteCarloParams,
    PortfolioMonteCarloRequest,
    PortfolioMonteCarloResponse,
    PortfolioPositionIn,
)


def _fund(i: int) -> dict[str, str]:
    return {"kind": "fund", "id": str(uuid.UUID(f"00000000-0000-0000-0000-00000000000{i}"))}


def test_request_defaults() -> None:
    req = PortfolioMonteCarloRequest.model_validate(
        {
            "positions": [
                {"asset": _fund(1), "weight": 0.6},
                {"asset": _fund(2), "weight": 0.4},
            ]
        }
    )
    assert req.statistic == "max_drawdown"
    assert req.n_simulations == 10_000
    assert req.horizons is None
    assert req.risk_free_rate == pytest.approx(0.04)
    assert req.seed is None
    assert req.window_days is None
    assert len(req.positions) == 2


def test_request_requires_at_least_two_positions() -> None:
    with pytest.raises(ValidationError):
        PortfolioMonteCarloRequest.model_validate(
            {"positions": [{"asset": _fund(1), "weight": 1.0}]}
        )


def test_request_position_weight_bounds() -> None:
    with pytest.raises(ValidationError):
        PortfolioPositionIn.model_validate({"asset": _fund(1), "weight": 0.0})
    with pytest.raises(ValidationError):
        PortfolioPositionIn.model_validate({"asset": _fund(1), "weight": 1.5})


def test_request_rejects_unknown_statistic() -> None:
    with pytest.raises(ValidationError):
        PortfolioMonteCarloRequest.model_validate(
            {
                "positions": [
                    {"asset": _fund(1), "weight": 0.5},
                    {"asset": _fund(2), "weight": 0.5},
                ],
                "statistic": "median",
            }
        )


def test_response_params_have_n_assets_not_ticker() -> None:
    params = PortfolioMonteCarloParams(
        statistic="return",
        n_assets=3,
        n_simulations=10_000,
        risk_free_rate=0.04,
        seed=7,
    )
    dumped = params.model_dump()
    assert dumped["n_assets"] == 3
    assert "ticker" not in dumped


def test_response_round_trips_confidence_bars() -> None:
    from app.schemas.monte_carlo import ConfidenceBar

    resp = PortfolioMonteCarloResponse(
        params=PortfolioMonteCarloParams(
            statistic="return",
            n_assets=2,
            n_simulations=10_000,
            risk_free_rate=0.04,
            seed=None,
        ),
        percentiles={"50th": 0.05},
        mean=0.05,
        median=0.05,
        std=0.01,
        historical_value=0.04,
        historical_horizon_days=500,
        historical_percentile_rank=42.0,
        confidence_bars=[
            ConfidenceBar(
                horizon="1Y",
                horizon_days=252,
                pct_5=-0.1,
                pct_10=-0.05,
                pct_25=0.0,
                pct_50=0.05,
                pct_75=0.1,
                pct_90=0.15,
                pct_95=0.2,
                mean=0.05,
            )
        ],
        degraded=False,
        degraded_reason=None,
    )
    dumped = resp.model_dump()
    assert dumped["confidence_bars"][0]["horizon"] == "1Y"
    assert dumped["historical_percentile_rank"] == 42.0
    assert dumped["params"]["n_assets"] == 2
