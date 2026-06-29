"""Tests for the correlation-regime schema (T3F-6) and route (T3F-7).

Schema section pins field shapes/validators; route section (T3F-7) stubs the
service and asserts the wire payload + 422 mapping.
"""

import pytest

from app.schemas.correlation_regime import (
    ConcentrationOut,
    CorrelationRegimeOut,
    CorrelationRegimeRequest,
    PairCorrelationOut,
)

# ── T3F-6: schema validation ─────────────────────────────────────────────────


def _concentration() -> ConcentrationOut:
    return ConcentrationOut(
        eigenvalues=[3.1, 0.5, 0.4],
        first_eigenvalue_ratio=0.7,
        concentration_status="moderate_concentration",
        absorption_ratio=0.82,
        absorption_status="warning",
        mp_threshold=1.58,
        n_signal_eigenvalues=1,
    )


def test_correlation_regime_out_roundtrip() -> None:
    out = CorrelationRegimeOut(
        instrument_count=2,
        labels=["fund:a", "fund:b"],
        window_days=60,
        correlation_matrix=[[1.0, 0.4], [0.4, 1.0]],
        pair_correlations=[
            PairCorrelationOut(
                label_a="fund:a",
                label_b="fund:b",
                current_correlation=0.4,
                baseline_correlation=0.2,
                correlation_change=0.2,
                is_contagion=False,
            )
        ],
        concentration=_concentration(),
        diversification_ratio=1.3,
        dr_alert=False,
        average_correlation=0.4,
        baseline_average_correlation=0.2,
        regime_shift_detected=False,
        sufficient_data=True,
    )
    dumped = out.model_dump()
    assert dumped["instrument_count"] == 2
    assert dumped["pair_correlations"][0]["is_contagion"] is False
    assert dumped["concentration"]["absorption_status"] == "warning"


def test_request_requires_exactly_one_source() -> None:
    with pytest.raises(ValueError, match="exactly one"):
        CorrelationRegimeRequest()  # neither assets nor universe


def test_request_rejects_both_sources() -> None:
    with pytest.raises(ValueError, match="exactly one"):
        CorrelationRegimeRequest(
            assets=[{"kind": "equity", "ticker": "SPY"}, {"kind": "equity", "ticker": "QQQ"}],
            universe={"max_assets": 5},
        )


def test_request_accepts_explicit_assets() -> None:
    req = CorrelationRegimeRequest(
        assets=[{"kind": "equity", "ticker": "SPY"}, {"kind": "equity", "ticker": "QQQ"}]
    )
    assert req.assets is not None and len(req.assets) == 2
    assert req.universe is None


def test_request_window_days_bounds() -> None:
    with pytest.raises(ValueError):
        CorrelationRegimeRequest(
            assets=[{"kind": "equity", "ticker": "SPY"}, {"kind": "equity", "ticker": "QQQ"}],
            window_days=10,  # below the 30 floor
        )


# ── T3F-7: route ─────────────────────────────────────────────────────────────

from httpx import ASGITransport, AsyncClient  # noqa: E402

from app.core.db import get_session  # noqa: E402
from app.main import create_app  # noqa: E402
from app.services import correlation_regime as cr_service  # noqa: E402


def _route_client() -> AsyncClient:
    app = create_app()
    app.dependency_overrides[get_session] = lambda: None
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


def _sample_out() -> CorrelationRegimeOut:
    return CorrelationRegimeOut(
        instrument_count=2,
        labels=["equity:SPY", "equity:QQQ"],
        window_days=60,
        correlation_matrix=[[1.0, 0.85], [0.85, 1.0]],
        pair_correlations=[
            PairCorrelationOut(
                label_a="equity:SPY",
                label_b="equity:QQQ",
                current_correlation=0.85,
                baseline_correlation=0.5,
                correlation_change=0.35,
                is_contagion=True,
            )
        ],
        concentration=_concentration(),
        diversification_ratio=1.05,
        dr_alert=True,
        average_correlation=0.85,
        baseline_average_correlation=0.5,
        regime_shift_detected=True,
        sufficient_data=True,
    )


async def test_route_returns_regime_payload(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_run(session, refs, window_days=None, today=None):
        # Echo that the two equity refs were translated correctly.
        assert [r.label for r in refs] == ["equity:SPY", "equity:QQQ"]
        return _sample_out()

    monkeypatch.setattr(cr_service, "run_correlation_regime", fake_run)
    async with _route_client() as client:
        resp = await client.post(
            "/correlation-regime",
            json={
                "assets": [
                    {"kind": "equity", "ticker": "SPY"},
                    {"kind": "equity", "ticker": "QQQ"},
                ]
            },
        )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["regime_shift_detected"] is True
    assert body["pair_correlations"][0]["is_contagion"] is True
    assert body["concentration"]["absorption_status"] == "warning"


async def test_route_maps_value_error_to_422(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_run(session, refs, window_days=None, today=None):
        raise ValueError("insufficient common history: 12 overlapping observations")

    monkeypatch.setattr(cr_service, "run_correlation_regime", fake_run)
    async with _route_client() as client:
        resp = await client.post(
            "/correlation-regime",
            json={
                "assets": [
                    {"kind": "equity", "ticker": "SPY"},
                    {"kind": "equity", "ticker": "QQQ"},
                ]
            },
        )
    assert resp.status_code == 422
    assert "insufficient common history" in resp.json()["detail"]


async def test_route_rejects_missing_source_422() -> None:
    async with _route_client() as client:
        resp = await client.post("/correlation-regime", json={})
    # Pydantic request validation → 422.
    assert resp.status_code == 422
