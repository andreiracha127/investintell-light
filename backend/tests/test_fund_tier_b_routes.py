"""Tests for P5 Backend Tier B fund dossier routes.

Services are stubbed at ``app.services.fund_dossier_tier_b``; no live DB.
"""

import datetime as dt
import uuid

import pytest
from httpx import ASGITransport, AsyncClient

from app.core.datalake import get_datalake_session
from app.core.db import get_session
from app.main import create_app
from app.schemas.fund_analysis import (
    EmptyState,
    FundActiveShareResponse,
    FundCaptureRatios,
    FundDrawdownAnalysis,
    FundEntityAnalyticsResponse,
    FundFactorsResponse,
    FundMarketSensitivity,
    FundRegimeBand,
    FundReturnDistribution,
    FundReturnStatistics,
    FundRiskStatistics,
    FundRiskTimeseriesResponse,
    FundRollingReturns,
    FundSourceMetadata,
    FundStyleBias,
    FundStyleDriftPeriod,
    FundStyleDriftResponse,
    FundStyleSectorWeight,
    FundTailRiskMetrics,
)
from app.services import fund_dossier_tier_b as tier_b

_FUND_ID = uuid.UUID("00000000-0000-0000-0000-000000000001")
_BENCH_ID = uuid.UUID("00000000-0000-0000-0000-000000000002")


def _client() -> AsyncClient:
    app = create_app()
    app.dependency_overrides[get_session] = lambda: None
    app.dependency_overrides[get_datalake_session] = lambda: None
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


def _factors_payload() -> FundFactorsResponse:
    return FundFactorsResponse(
        instrument_id=_FUND_ID,
        market_sensitivities=[
            FundMarketSensitivity(factor="Factor 1", beta=0.7, t_stat=2.2, significance="**")
        ],
        style_bias=[
            FundStyleBias(
                factor="momentum",
                value=0.4,
                z_score=1.1,
                as_of=dt.date(2026, 3, 31),
            )
        ],
        source_metadata=[
            FundSourceMetadata(source="factor_model_fits", as_of=dt.date(2026, 3, 31))
        ],
    )


def _style_payload() -> FundStyleDriftResponse:
    return FundStyleDriftResponse(
        instrument_id=_FUND_ID,
        series_id="S000000001",
        periods=[
            FundStyleDriftPeriod(
                report_date=dt.date(2026, 3, 31),
                quarter="2026Q1",
                sectors=[FundStyleSectorWeight(sector="Technology", weight=0.25)],
            )
        ],
    )


def _entity_payload() -> FundEntityAnalyticsResponse:
    return FundEntityAnalyticsResponse(
        instrument_id=_FUND_ID,
        name="Sample Fund",
        as_of_date=dt.date(2026, 6, 12),
        window="1Y",
        risk_statistics=FundRiskStatistics(
            annualized_return=0.1,
            annualized_volatility=0.2,
            sharpe_ratio=0.3,
            n_observations=252,
        ),
        drawdown=FundDrawdownAnalysis(
            dates=[dt.date(2026, 6, 12)],
            values=[-0.05],
            max_drawdown=-0.05,
            current_drawdown=-0.01,
            worst_periods=[],
        ),
        capture=FundCaptureRatios(
            benchmark_id=_BENCH_ID,
            benchmark_label="Benchmark Fund",
            up_periods=3,
            down_periods=2,
        ),
        rolling_returns=FundRollingReturns(
            series={"1M": [], "3M": [], "6M": [], "1Y": []}
        ),
        distribution=FundReturnDistribution(
            bin_edges=[-0.01, 0.0, 0.01],
            bin_counts=[2, 3],
            var_95=0.02,
            cvar_95=0.03,
        ),
        return_statistics=FundReturnStatistics(arithmetic_mean_monthly=0.01),
        tail_risk=FundTailRiskMetrics(var_parametric_95=0.02, etl_95=0.03),
        insider_data=None,
    )


def _risk_ts_payload() -> FundRiskTimeseriesResponse:
    return FundRiskTimeseriesResponse(
        instrument_id=_FUND_ID,
        drawdown=[(dt.date(2026, 6, 12), -5.0)],
        conditional_volatility=[(dt.date(2026, 6, 12), 12.0)],
        volatility_model="ewma",
        regime_bands=[
            FundRegimeBand(time=dt.date(2026, 6, 12), value=0.5, regime="Cautious")
        ],
    )


def _active_share_payload() -> FundActiveShareResponse:
    return FundActiveShareResponse(
        instrument_id=_FUND_ID,
        benchmark_id=_BENCH_ID,
        benchmark_name="Benchmark Fund",
        active_share=0.42,
        overlap=0.58,
        n_portfolio_positions=10,
        n_benchmark_positions=12,
        n_common_positions=4,
        as_of_date=dt.date(2026, 3, 31),
    )


async def test_fund_factors_success(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_fetch(session, datalake, instrument_id):
        assert instrument_id == _FUND_ID
        return _factors_payload()

    monkeypatch.setattr(tier_b, "fetch_fund_factors", fake_fetch)
    async with _client() as client:
        resp = await client.get(f"/funds/{_FUND_ID}/factors")
    assert resp.status_code == 200
    assert resp.json()["market_sensitivities"][0]["significance"] == "**"


async def test_fund_factors_missing_fund_404(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_fetch(*args, **kwargs):
        return None

    monkeypatch.setattr(tier_b, "fetch_fund_factors", fake_fetch)
    async with _client() as client:
        resp = await client.get(f"/funds/{_FUND_ID}/factors")
    assert resp.status_code == 404


async def test_fund_style_drift_success(monkeypatch: pytest.MonkeyPatch) -> None:
    seen = {}

    async def fake_fetch(session, datalake, instrument_id, *, quarters):
        seen.update(instrument_id=instrument_id, quarters=quarters)
        return _style_payload()

    monkeypatch.setattr(tier_b, "fetch_fund_style_drift", fake_fetch)
    async with _client() as client:
        resp = await client.get(f"/funds/{_FUND_ID}/style-drift", params={"quarters": 4})
    assert resp.status_code == 200
    assert resp.json()["periods"][0]["quarter"] == "2026Q1"
    assert seen == {"instrument_id": _FUND_ID, "quarters": 4}


@pytest.mark.parametrize("quarters", [0, 21])
async def test_fund_style_drift_quarter_bounds(quarters: int) -> None:
    async with _client() as client:
        resp = await client.get(
            f"/funds/{_FUND_ID}/style-drift", params={"quarters": quarters}
        )
    assert resp.status_code == 422


async def test_fund_entity_analytics_success(monkeypatch: pytest.MonkeyPatch) -> None:
    seen = {}

    async def fake_fetch(session, instrument_id, *, window, benchmark_id):
        seen.update(instrument_id=instrument_id, window=window, benchmark_id=benchmark_id)
        return _entity_payload()

    monkeypatch.setattr(tier_b, "fetch_fund_entity_analytics", fake_fetch)
    async with _client() as client:
        resp = await client.get(
            f"/funds/{_FUND_ID}/entity-analytics",
            params={"window": "1Y", "benchmark_id": str(_BENCH_ID)},
        )
    assert resp.status_code == 200
    assert resp.json()["tail_risk"]["var_parametric_95"] == 0.02
    assert seen == {
        "instrument_id": _FUND_ID,
        "window": "1Y",
        "benchmark_id": _BENCH_ID,
    }


async def test_fund_entity_analytics_invalid_benchmark_422(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fake_fetch(*args, **kwargs):
        raise tier_b.InvalidBenchmarkError("Benchmark fund missing")

    monkeypatch.setattr(tier_b, "fetch_fund_entity_analytics", fake_fetch)
    async with _client() as client:
        resp = await client.get(f"/funds/{_FUND_ID}/entity-analytics")
    assert resp.status_code == 422
    assert "Benchmark" in resp.json()["detail"]


async def test_fund_risk_timeseries_success(monkeypatch: pytest.MonkeyPatch) -> None:
    seen = {}

    async def fake_fetch(session, datalake, instrument_id, *, from_date, to_date):
        seen.update(instrument_id=instrument_id, from_date=from_date, to_date=to_date)
        return _risk_ts_payload()

    monkeypatch.setattr(tier_b, "fetch_fund_risk_timeseries", fake_fetch)
    async with _client() as client:
        resp = await client.get(
            f"/funds/{_FUND_ID}/risk-timeseries",
            params={"from": "2026-01-01", "to": "2026-06-12"},
        )
    assert resp.status_code == 200
    assert resp.json()["drawdown"][0][1] == -5.0
    assert seen["from_date"] == dt.date(2026, 1, 1)


async def test_fund_active_share_empty_without_benchmark(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fake_fetch(session, datalake, instrument_id, *, benchmark_id):
        assert benchmark_id is None
        return FundActiveShareResponse(
            instrument_id=instrument_id,
            empty_state=EmptyState(reason="benchmark_id is required"),
        )

    monkeypatch.setattr(tier_b, "fetch_fund_active_share", fake_fetch)
    async with _client() as client:
        resp = await client.get(f"/funds/{_FUND_ID}/active-share")
    assert resp.status_code == 200
    assert resp.json()["active_share"] is None
    assert "benchmark_id" in resp.json()["empty_state"]["reason"]


async def test_fund_active_share_success(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_fetch(session, datalake, instrument_id, *, benchmark_id):
        assert benchmark_id == _BENCH_ID
        return _active_share_payload()

    monkeypatch.setattr(tier_b, "fetch_fund_active_share", fake_fetch)
    async with _client() as client:
        resp = await client.get(
            f"/funds/{_FUND_ID}/active-share",
            params={"benchmark_id": str(_BENCH_ID)},
        )
    assert resp.status_code == 200
    assert resp.json()["active_share"] == 0.42
