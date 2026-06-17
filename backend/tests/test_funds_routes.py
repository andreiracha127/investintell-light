"""Tests for the funds routes (app/api/routes/funds.py).

The catalog service is stubbed at its canonical module
(``app.services.funds_catalog``) — no live network, no live DB. The pure
CSV pipeline stays LIVE in the CSV test (only the SQL read is stubbed).
"""

import datetime as dt
import uuid
from types import SimpleNamespace
from typing import Any

import pytest
from httpx import ASGITransport, AsyncClient

from app.core.db import get_session
from app.main import create_app
from app.services import funds_catalog as catalog

_FUND_ID = uuid.UUID("00000000-0000-0000-0000-000000000001")
_SYNCED = dt.datetime(2026, 6, 11, 3, 0, tzinfo=dt.UTC)
_CALC = dt.date(2026, 6, 9)
_NAVMAX = dt.date(2026, 6, 5)

_STALENESS = catalog.Staleness(
    synced_at=_SYNCED, source_calc_date=_CALC, source_nav_max_date=_NAVMAX
)


def _item_row(**overrides: Any) -> dict[str, Any]:
    row: dict[str, Any] = {
        "instrument_id": _FUND_ID,
        "series_id": "S000012345",
        "ticker": "VTI",
        "name": "Vanguard Total Stock Market ETF",
        "fund_type": "etf",
        "strategy_label": "Large Cap Blend",
        "asset_class": "equity",
        "is_index": True,
        "expense_ratio": 0.0003,
        "aum_usd": 3.5e11,
        "return_1y": 0.12,
        "volatility_1y": 0.15,
        "sharpe_1y": 1.1,
        "max_drawdown_1y": -0.08,
        "peer_sharpe_pctl": 0.93,
        "manager_score": 88.5,
        "elite_flag": True,
    }
    row.update(overrides)
    return row


def _client() -> AsyncClient:
    app = create_app()
    app.dependency_overrides[get_session] = lambda: None
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


def _stub_list(
    monkeypatch: pytest.MonkeyPatch,
    rows: list[dict[str, Any]],
    total: int,
    calls: list[dict[str, Any]] | None = None,
) -> None:
    async def fetch_funds(
        session: Any, filters: catalog.FundFilters, **kwargs: Any
    ) -> tuple[list[dict[str, Any]], int]:
        if calls is not None:
            calls.append({"filters": filters, **kwargs})
        return rows, total

    async def fetch_staleness(session: Any) -> catalog.Staleness:
        return _STALENESS

    monkeypatch.setattr(catalog, "fetch_funds", fetch_funds)
    monkeypatch.setattr(catalog, "fetch_staleness", fetch_staleness)


# ---------------------------------------------------------------------------
# GET /funds
# ---------------------------------------------------------------------------


async def test_list_funds_payload(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[dict[str, Any]] = []
    _stub_list(monkeypatch, [_item_row()], 4558, calls)
    async with _client() as client:
        resp = await client.get("/funds")
    assert resp.status_code == 200
    body = resp.json()
    assert body["total"] == 4558
    assert body["page"] == 1
    assert body["page_size"] == 50
    assert body["staleness"] == {
        "synced_at": "2026-06-11T03:00:00Z",
        "source_calc_date": "2026-06-09",
        "source_nav_max_date": "2026-06-05",
    }
    assert "classificador" in body["classification_note"]
    item = body["items"][0]
    assert item["instrument_id"] == str(_FUND_ID)
    assert item["sharpe_1y"] == 1.1
    assert item["manager_score"] == 88.5
    assert item["elite_flag"] is True
    # Defaults reach the service: aum_usd desc, page 1 -> offset 0.
    assert calls[0]["sort"] == "aum_usd"
    assert calls[0]["direction"] == "desc"
    assert calls[0]["limit"] == 50
    assert calls[0]["offset"] == 0


async def test_list_funds_filters_and_pagination_reach_service(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[dict[str, Any]] = []
    _stub_list(monkeypatch, [], 0, calls)
    async with _client() as client:
        resp = await client.get(
            "/funds",
            params={
                "search": "vang",
                "fund_type": "etf",
                "strategy_label": "Large",
                "asset_class": "equity",
                "expense_ratio_max": 0.01,
                "aum_min": 1e8,
                "sharpe_1y_min": 0.5,
                "volatility_1y_max": 0.25,
                "return_1y_min": 0.0,
                "max_drawdown_1y_min": -0.3,
                "sort": "sharpe_1y",
                "dir": "asc",
                "page": 3,
                "page_size": 100,
            },
        )
    assert resp.status_code == 200
    call = calls[0]
    assert call["filters"] == catalog.FundFilters(
        search="vang",
        fund_type="etf",
        strategy_label="Large",
        asset_class="equity",
        expense_ratio_max=0.01,
        aum_min=1e8,
        sharpe_1y_min=0.5,
        volatility_1y_max=0.25,
        return_1y_min=0.0,
        max_drawdown_1y_min=-0.3,
    )
    assert call["sort"] == "sharpe_1y"
    assert call["direction"] == "asc"
    assert call["limit"] == 100
    assert call["offset"] == 200


@pytest.mark.parametrize(
    "params",
    [
        {"sort": "synced_at_x"},
        {"sort": "aum_usd; DROP TABLE funds;--"},
        {"fund_type": "hedge"},
        {"asset_class": "crypto"},
        {"page": 0},
        {"page_size": 201},
        {"dir": "sideways"},
    ],
)
async def test_list_funds_rejects_bad_params(
    monkeypatch: pytest.MonkeyPatch, params: dict[str, Any]
) -> None:
    _stub_list(monkeypatch, [], 0)
    async with _client() as client:
        resp = await client.get("/funds", params=params)
    assert resp.status_code == 422


async def test_list_funds_empty_universe_is_200(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fetch_funds(*args: Any, **kwargs: Any) -> tuple[list[Any], int]:
        return [], 0

    async def fetch_staleness(session: Any) -> catalog.Staleness:
        return catalog.Staleness(None, None, None)

    monkeypatch.setattr(catalog, "fetch_funds", fetch_funds)
    monkeypatch.setattr(catalog, "fetch_staleness", fetch_staleness)
    async with _client() as client:
        resp = await client.get("/funds")
    assert resp.status_code == 200
    body = resp.json()
    assert body["total"] == 0
    assert body["staleness"]["synced_at"] is None


# ---------------------------------------------------------------------------
# GET /funds.csv
# ---------------------------------------------------------------------------


async def test_funds_csv_header_and_cap(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[dict[str, Any]] = []
    _stub_list(monkeypatch, [_item_row()], 1, calls)
    async with _client() as client:
        resp = await client.get("/funds.csv", params={"fund_type": "etf"})
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("text/csv")
    assert 'filename="funds.csv"' in resp.headers["content-disposition"]
    lines = resp.text.splitlines()
    assert lines[0].startswith("ticker,name,fund_type,strategy_label,")
    assert lines[1].startswith("VTI,Vanguard Total Stock Market ETF,etf,")
    # Unpaginated: the service is called with the hard cap, offset 0.
    assert calls[0]["limit"] == catalog.CSV_HARD_CAP == 5000
    assert calls[0]["offset"] == 0


async def test_funds_csv_rejects_bad_sort(monkeypatch: pytest.MonkeyPatch) -> None:
    _stub_list(monkeypatch, [], 0)
    async with _client() as client:
        resp = await client.get("/funds.csv", params={"sort": "evil"})
    assert resp.status_code == 422


# ---------------------------------------------------------------------------
# GET /funds/{instrument_id}
# ---------------------------------------------------------------------------


def _profile() -> catalog.FundProfile:
    fund = SimpleNamespace(
        instrument_id=_FUND_ID,
        series_id="S000012345",
        ticker="VTI",
        isin="US9229087690",
        cusip="922908769",
        lei=None,
        name="Vanguard Total Stock Market ETF",
        fund_type="etf",
        strategy_label="Large Cap Blend",
        asset_class="equity",
        is_index=True,
        expense_ratio=0.0003,
        aum_usd=3.5e11,
        primary_benchmark="CRSP US Total Market",
        inception_date=dt.date(2001, 5, 24),
        domicile="US",
        currency="USD",
        synced_at=_SYNCED,
        source_calc_date=_CALC,
        source_nav_max_date=_NAVMAX,
    )
    risk_fields = {
        name: None
        for name in catalog.SORT_WHITELIST
        if name not in (
            "ticker", "name", "fund_type", "strategy_label", "asset_class",
            "expense_ratio", "aum_usd", "inception_date",
        )
    }
    risk = SimpleNamespace(
        **{
            **risk_fields,
            "calc_date": _CALC,
            "sharpe_1y": 1.1,
            "cvar_95_12m": -0.21,
            "peer_strategy_label": "Large Cap Blend",
            "peer_count": 412,
            "elite_flag": True,
            "empirical_duration": 6.4,
            "credit_beta": 1.2,
            "inflation_beta": 0.35,
            "crisis_alpha_score": 0.042,
        }
    )
    holding = SimpleNamespace(
        rank=1,
        issuer_name="Apple Inc",
        cusip="037833100",
        isin="US0378331005",
        asset_class="EC",
        sector="CORP",  # N-PORT issuerCat code — not a real sector
        gics_sector="Information Technology",  # the real (mapped) sector
        market_value=2.1e10,
        pct_of_nav=0.061,
    )
    # Classes arrive from the service already ordered expense_ratio asc
    # NULLS LAST (F8.6b) — the route serializes them in order.
    fund_class = SimpleNamespace(
        class_id="C000001",
        class_name="Institutional",
        ticker="VITSX",
        expense_ratio=0.0002,
    )
    fund_class_no_fee = SimpleNamespace(
        class_id="C000002", class_name=None, ticker="VTSAX", expense_ratio=None
    )
    return catalog.FundProfile(
        fund=fund,  # type: ignore[arg-type]
        risk=risk,  # type: ignore[arg-type]
        nav=[(dt.date(2026, 6, 4), 305.1), (dt.date(2026, 6, 5), 306.2)],
        holdings=[holding],  # type: ignore[list-item]
        holdings_report_date=dt.date(2026, 5, 31),
        holdings_pct_of_nav_total=0.61,
        classes=[fund_class, fund_class_no_fee],  # type: ignore[list-item]
    )


async def test_fund_profile_payload(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fetch_fund_profile(
        session: Any, instrument_id: uuid.UUID
    ) -> catalog.FundProfile:
        assert instrument_id == _FUND_ID
        return _profile()

    monkeypatch.setattr(catalog, "fetch_fund_profile", fetch_fund_profile)
    async with _client() as client:
        resp = await client.get(f"/funds/{_FUND_ID}")
    assert resp.status_code == 200
    body = resp.json()
    assert body["ticker"] == "VTI"
    assert body["risk"]["sharpe_1y"] == 1.1
    assert body["risk"]["cvar_95_12m"] == -0.21
    assert body["risk"]["peer_count"] == 412
    assert body["risk"]["empirical_duration"] == 6.4
    assert body["risk"]["credit_beta"] == 1.2
    assert body["risk"]["inflation_beta"] == 0.35
    assert body["risk"]["crisis_alpha_score"] == 0.042
    assert body["nav"] == [
        {"date": "2026-06-04", "nav": 305.1},
        {"date": "2026-06-05", "nav": 306.2},
    ]
    holdings = body["holdings"]
    assert holdings["report_date"] == "2026-05-31"
    assert holdings["pct_of_nav_total"] == 0.61
    assert holdings["items"][0]["issuer_name"] == "Apple Inc"
    # The real sector travels in gics_sector; sector stays the N-PORT code.
    assert holdings["items"][0]["gics_sector"] == "Information Technology"
    assert holdings["items"][0]["sector"] == "CORP"
    # F8.6b share classes, service order preserved (expense asc NULLS LAST).
    assert body["classes"] == [
        {
            "class_id": "C000001",
            "class_name": "Institutional",
            "ticker": "VITSX",
            "expense_ratio": 0.0002,
        },
        {
            "class_id": "C000002",
            "class_name": None,
            "ticker": "VTSAX",
            "expense_ratio": None,
        },
    ]
    assert "classificador" in body["classification_note"]


async def test_fund_profile_404(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fetch_fund_profile(session: Any, instrument_id: uuid.UUID) -> None:
        return None

    monkeypatch.setattr(catalog, "fetch_fund_profile", fetch_fund_profile)
    async with _client() as client:
        resp = await client.get(f"/funds/{uuid.uuid4()}")
    assert resp.status_code == 404


async def test_fund_profile_bad_uuid_is_422() -> None:
    async with _client() as client:
        resp = await client.get("/funds/not-a-uuid")
    assert resp.status_code == 422
