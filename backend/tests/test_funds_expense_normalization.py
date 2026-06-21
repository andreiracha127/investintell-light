"""T3D-3 — expense_ratio is normalized to a decimal fraction at the read seam."""

import uuid
from types import SimpleNamespace

import pytest
from httpx import ASGITransport, AsyncClient

from app.api.routes import funds as funds_route
from app.core.auth import CurrentUser, get_current_user
from app.core.datalake import get_optional_datalake_session
from app.core.db import get_session
from app.main import create_app

_IID = uuid.UUID("00000000-0000-0000-0000-0000000000ff")


def _client() -> AsyncClient:
    app = create_app()
    app.dependency_overrides[get_session] = lambda: None
    app.dependency_overrides[get_optional_datalake_session] = lambda: None
    app.dependency_overrides[get_current_user] = lambda: CurrentUser(
        sub="u-1", org_id=None, claims={}
    )
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


def _fund(expense_ratio: float | None) -> SimpleNamespace:
    return SimpleNamespace(
        instrument_id=_IID,
        series_id="S000",
        ticker="ABC",
        isin=None,
        cusip=None,
        lei=None,
        name="Fund ABC",
        fund_type="etf",
        strategy_label="Unclassified",
        asset_class="equity",
        is_index=False,
        expense_ratio=expense_ratio,
        aum_usd=None,
        primary_benchmark=None,
        inception_date=None,
        domicile=None,
        currency="USD",
    )


def _profile(fund: SimpleNamespace) -> SimpleNamespace:
    return SimpleNamespace(
        fund=fund,
        benchmark=None,
        risk=None,
        nav=[],
        holdings=[],
        holdings_report_date=None,
        holdings_pct_of_nav_total=None,
        classes=[],
    )


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("stored", "served"),
    [
        (1.5, 0.015),      # whole percent -> fraction
        (150.0, 0.015),    # basis points -> fraction
        (0.0069, 0.0069),  # canonical fraction unchanged
    ],
)
async def test_profile_expense_ratio_is_normalized(
    monkeypatch: pytest.MonkeyPatch, stored: float, served: float
) -> None:
    async def fake_fetch(session, instrument_id):
        return _profile(_fund(stored))

    monkeypatch.setattr(funds_route.catalog, "fetch_fund_profile", fake_fetch)
    async with _client() as client:
        resp = await client.get(f"/funds/{_IID}")
    assert resp.status_code == 200
    assert resp.json()["expense_ratio"] == pytest.approx(served)


@pytest.mark.anyio
async def test_profile_expense_ratio_none_stays_none(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fake_fetch(session, instrument_id):
        return _profile(_fund(None))

    monkeypatch.setattr(funds_route.catalog, "fetch_fund_profile", fake_fetch)
    async with _client() as client:
        resp = await client.get(f"/funds/{_IID}")
    assert resp.status_code == 200
    assert resp.json()["expense_ratio"] is None
