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
    FundInstitutionalRevealResponse,
    FundRegimeBand,
    FundReturnDistribution,
    FundReturnStatistics,
    FundRiskStatistics,
    FundRiskTimeseriesResponse,
    FundRollingReturns,
    FundSourceMetadata,
    HolderNetwork,
    HolderNetworkEdge,
    HolderNetworkNode,
    HoldingReverseLookupResponse,
    InsiderData,
    InsiderQuarterSentiment,
    InstitutionalHolder,
    InstitutionalOverlapSecurity,
    ReverseLookupFundExposure,
    ReverseLookupInstitution,
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
        insider_data=InsiderData(
            issuer_ciks=["320193"],
            matched_cusips=["037833100"],
            quarters=[
                InsiderQuarterSentiment(
                    quarter=dt.date(2026, 1, 1),
                    buy_value=125.0,
                    sell_value=80.0,
                    net_value=45.0,
                    buy_count=1,
                    sell_count=1,
                )
            ],
            total_buy_value=125.0,
            total_sell_value=80.0,
            net_value=45.0,
            sentiment_score=0.2195121951,
            as_of=dt.date(2026, 1, 1),
        ),
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


def _institutional_payload() -> FundInstitutionalRevealResponse:
    return FundInstitutionalRevealResponse(
        instrument_id=_FUND_ID,
        series_id="S000000001",
        fund_name="Sample Fund",
        holdings_report_date=dt.date(2026, 3, 31),
        period=dt.date(2026, 3, 31),
        top_holders=[
            InstitutionalHolder(
                cik="1067983",
                manager_name="Berkshire Hathaway",
                value_usd=123000.0,
                shares=4500.0,
                holding_count=1,
                period=dt.date(2026, 3, 31),
                report_date=dt.date(2026, 3, 31),
            )
        ],
        overlap=[
            InstitutionalOverlapSecurity(
                cusip="037833100",
                name="APPLE INC",
                fund_pct_of_nav=7.1,
                institutional_value_usd=123000.0,
                institution_count=1,
                top_managers=["Berkshire Hathaway"],
            )
        ],
        holder_network=HolderNetwork(
            nodes=[
                HolderNetworkNode(id=f"fund:{_FUND_ID}", label="Sample Fund", type="fund"),
                HolderNetworkNode(id="institution:1067983", label="Berkshire Hathaway", type="institution"),
                HolderNetworkNode(id="security:037833100", label="APPLE INC", type="security"),
            ],
            edges=[
                HolderNetworkEdge(
                    source=f"fund:{_FUND_ID}",
                    target="security:037833100",
                    weight=7.1,
                    label="fund holding",
                )
            ],
        ),
    )


def _reverse_lookup_payload() -> HoldingReverseLookupResponse:
    return HoldingReverseLookupResponse(
        cusip="037833100",
        security_name="APPLE INC",
        period=dt.date(2026, 3, 31),
        institutions=[
            ReverseLookupInstitution(
                cik="1067983",
                manager_name="Berkshire Hathaway",
                value_usd=123000.0,
                shares=4500.0,
                period=dt.date(2026, 3, 31),
                report_date=dt.date(2026, 3, 31),
            )
        ],
        fund_exposures=[
            ReverseLookupFundExposure(
                instrument_id=_FUND_ID,
                series_id="S000000001",
                ticker="SAMP",
                name="Sample Fund",
                issuer_name="APPLE INC",
                pct_of_nav=7.1,
                market_value=100000.0,
                report_date=dt.date(2026, 3, 31),
            )
        ],
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

    async def fake_fetch(session, datalake, instrument_id, *, window, benchmark_id):
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
    assert resp.json()["insider_data"]["net_value"] == 45.0
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


async def test_fund_institutional_reveal_success(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fake_fetch(session, datalake, instrument_id):
        assert instrument_id == _FUND_ID
        return _institutional_payload()

    monkeypatch.setattr(tier_b, "fetch_fund_institutional_reveal", fake_fetch)
    async with _client() as client:
        resp = await client.get(f"/funds/{_FUND_ID}/institutional-reveal")
    assert resp.status_code == 200
    body = resp.json()
    assert body["top_holders"][0]["manager_name"] == "Berkshire Hathaway"
    assert body["overlap"][0]["cusip"] == "037833100"


async def test_fund_institutional_reveal_empty_state(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fake_fetch(session, datalake, instrument_id):
        return FundInstitutionalRevealResponse(
            instrument_id=instrument_id,
            series_id="S000000001",
            fund_name="Sample Fund",
            top_holders=[],
            overlap=[],
            holder_network=HolderNetwork(
                nodes=[HolderNetworkNode(id=f"fund:{instrument_id}", label="Sample Fund", type="fund")],
                edges=[],
            ),
            empty_state=EmptyState(
                reason="SEC 13F holdings tables are not deployed yet.",
                source="sec_13f_holdings",
            ),
        )

    monkeypatch.setattr(tier_b, "fetch_fund_institutional_reveal", fake_fetch)
    async with _client() as client:
        resp = await client.get(f"/funds/{_FUND_ID}/institutional-reveal")
    assert resp.status_code == 200
    assert "SEC 13F" in resp.json()["empty_state"]["reason"]


async def test_holding_reverse_lookup_success(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_fetch(session, datalake, cusip):
        assert cusip == "037833100"
        return _reverse_lookup_payload()

    monkeypatch.setattr(tier_b, "fetch_holding_reverse_lookup", fake_fetch)
    async with _client() as client:
        resp = await client.get("/holdings/037833100/reverse-lookup")
    assert resp.status_code == 200
    body = resp.json()
    assert body["institutions"][0]["cik"] == "1067983"
    assert body["fund_exposures"][0]["instrument_id"] == str(_FUND_ID)


async def test_holding_reverse_lookup_invalid_cusip_422(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fake_fetch(*args, **kwargs):
        raise ValueError("Invalid CUSIP 'bad!'.")

    monkeypatch.setattr(tier_b, "fetch_holding_reverse_lookup", fake_fetch)
    async with _client() as client:
        resp = await client.get("/holdings/bad!/reverse-lookup")
    assert resp.status_code == 422


async def test_holding_reverse_lookup_empty_state(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fake_fetch(session, datalake, cusip):
        return HoldingReverseLookupResponse(
            cusip="037833100",
            institutions=[],
            fund_exposures=[],
            empty_state=EmptyState(reason="No fund exposure or 13F institutional holder matched this CUSIP."),
        )

    monkeypatch.setattr(tier_b, "fetch_holding_reverse_lookup", fake_fetch)
    async with _client() as client:
        resp = await client.get("/holdings/037833100/reverse-lookup")
    assert resp.status_code == 200
    assert "No fund exposure" in resp.json()["empty_state"]["reason"]
