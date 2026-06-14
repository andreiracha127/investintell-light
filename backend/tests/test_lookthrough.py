"""Tests for the look-through consumption endpoints (Frente C, ADENDO §6).

The look-through is COMPUTED by the datalake worker (repo
investintell-datalake-workers, ``nport_lookthrough``) and materialized in the
TimescaleDB Cloud; the Light only CONSUMES the materialized tables. These
tests stub the service fetchers at their canonical module
(``app.services.lookthrough``) — no live cloud, no live DB; the pure
portfolio consolidation math is tested directly.
"""

import datetime as dt
import uuid
from types import SimpleNamespace

import pytest
from httpx import ASGITransport, AsyncClient

from app.core.auth import CurrentUser, get_current_user
from app.core.datalake import get_datalake_session
from app.core.db import get_session
from app.main import create_app
from app.services import lookthrough as lt
from app.services import portfolio_crud

_FUND_ID = uuid.UUID("00000000-0000-0000-0000-000000000001")
_REPORT = dt.date(2026, 1, 31)
_OLDEST = dt.date(2025, 12, 31)


def _series_lookthrough(series_id: str = "S000012345") -> lt.SeriesLookthrough:
    return lt.SeriesLookthrough(
        series_id=series_id,
        report_date=_REPORT,
        exposures=[
            lt.ExposureRow("issuer", "037833", "Apple Inc", 50.0, 30.0),
            lt.ExposureRow("issuer", "594918", "Microsoft", 0.0, 20.0),
            lt.ExposureRow("asset_class", "EC", None, 50.0, 50.0),
            lt.ExposureRow("sector", "Tech", None, 50.0, 50.0),
            lt.ExposureRow("currency", "USD", None, 50.0, 50.0),
        ],
        summary=lt.LookthroughSummary(
            sum_pct_total=100.0,
            direct_pct=50.0,
            indirect_pct=50.0,
            expanded_fund_pct=50.0,
            nondecomposable_fund_pct=0.0,
            derivatives_gross_pct=0.0,
            derivatives_net_pct=0.0,
            unidentified_pct=0.0,
            coverage_pct=100.2,
            n_holdings=12,
            n_children_expanded=1,
            oldest_report_date=_OLDEST,
        ),
    )


def _client() -> AsyncClient:
    app = create_app()
    app.dependency_overrides[get_session] = lambda: None
    app.dependency_overrides[get_datalake_session] = lambda: None
    app.dependency_overrides[get_current_user] = lambda: CurrentUser(
        sub="u-1", org_id=None, claims={}
    )
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


# ---------------------------------------------------------------------------
# GET /funds/{id}/lookthrough
# ---------------------------------------------------------------------------


async def _stub_fund(monkeypatch: pytest.MonkeyPatch, series_id: str | None):
    async def fake_series(session, instrument_id):
        assert instrument_id == _FUND_ID
        return series_id

    monkeypatch.setattr(lt, "get_fund_series", fake_series)


@pytest.mark.anyio
async def test_fund_lookthrough_returns_dimensions_and_summary(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    await _stub_fund(monkeypatch, "S000012345")

    async def fake_fetch(dl, series_id, dimension=None):
        assert series_id == "S000012345"
        assert dimension is None
        return _series_lookthrough()

    monkeypatch.setattr(lt, "fetch_series_lookthrough", fake_fetch)

    async with _client() as client:
        resp = await client.get(f"/funds/{_FUND_ID}/lookthrough")
    assert resp.status_code == 200
    body = resp.json()
    assert body["series_id"] == "S000012345"
    assert body["report_date"] == "2026-01-31"
    issuers = body["dimensions"]["issuer"]
    apple = next(r for r in issuers if r["key"] == "037833")
    assert apple["label"] == "Apple Inc"
    assert apple["direct_pct"] == 50.0
    assert apple["indirect_pct"] == 30.0
    assert apple["total_pct"] == 80.0
    # residual explícito + staleness em cadeia
    s = body["summary"]
    assert s["oldest_report_date"] == "2025-12-31"
    assert s["coverage_pct"] == 100.2
    assert s["derivatives_gross_pct"] == 0.0
    assert s["n_children_expanded"] == 1


@pytest.mark.anyio
async def test_fund_lookthrough_single_dimension_param(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    await _stub_fund(monkeypatch, "S000012345")
    seen: dict = {}

    async def fake_fetch(dl, series_id, dimension=None):
        seen["dimension"] = dimension
        data = _series_lookthrough()
        return lt.SeriesLookthrough(
            series_id=data.series_id,
            report_date=data.report_date,
            exposures=[r for r in data.exposures if r.dimension == dimension],
            summary=data.summary,
        )

    monkeypatch.setattr(lt, "fetch_series_lookthrough", fake_fetch)

    async with _client() as client:
        resp = await client.get(
            f"/funds/{_FUND_ID}/lookthrough", params={"dimension": "sector"}
        )
    assert resp.status_code == 200
    assert seen["dimension"] == "sector"
    body = resp.json()
    assert list(body["dimensions"].keys()) == ["sector"]

    async with _client() as client:
        resp = await client.get(
            f"/funds/{_FUND_ID}/lookthrough", params={"dimension": "bogus"}
        )
    assert resp.status_code == 422


@pytest.mark.anyio
async def test_fund_lookthrough_unknown_fund_404(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    await _stub_fund(monkeypatch, None)
    async with _client() as client:
        resp = await client.get(f"/funds/{_FUND_ID}/lookthrough")
    assert resp.status_code == 404


@pytest.mark.anyio
async def test_fund_lookthrough_not_materialized_404(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    await _stub_fund(monkeypatch, "S000099999")

    async def fake_fetch(dl, series_id, dimension=None):
        return None

    monkeypatch.setattr(lt, "fetch_series_lookthrough", fake_fetch)

    async with _client() as client:
        resp = await client.get(f"/funds/{_FUND_ID}/lookthrough")
    assert resp.status_code == 404
    assert "materializ" in resp.json()["detail"].lower()


# ---------------------------------------------------------------------------
# consolidate_portfolio — pure math
# ---------------------------------------------------------------------------


def test_consolidate_portfolio_weights_and_merges() -> None:
    a = _series_lookthrough("S_A")
    b = lt.SeriesLookthrough(
        series_id="S_B",
        report_date=_REPORT,
        exposures=[
            lt.ExposureRow("issuer", "037833", "Apple Inc", 100.0, 0.0),
            lt.ExposureRow("asset_class", "EC", None, 100.0, 0.0),
            lt.ExposureRow("sector", "Tech", None, 100.0, 0.0),
            lt.ExposureRow("currency", "USD", None, 100.0, 0.0),
        ],
        summary=lt.LookthroughSummary(
            sum_pct_total=100.0, direct_pct=100.0, indirect_pct=0.0,
            expanded_fund_pct=0.0, nondecomposable_fund_pct=0.0,
            derivatives_gross_pct=0.0, derivatives_net_pct=0.0,
            unidentified_pct=0.0, coverage_pct=None, n_holdings=1,
            n_children_expanded=0, oldest_report_date=dt.date(2025, 9, 30),
        ),
    )
    # 40% no fundo A, 40% no fundo B (fração do valor total do portfólio)
    rows, aggregates = lt.consolidate_portfolio([(0.40, a), (0.40, b)])

    by_key = {(r.dimension, r.key): r for r in rows}
    apple = by_key[("issuer", "037833")]
    # A: 0.4×(50+30)=32 ; B: 0.4×100=40 → total 72, direta 60, indireta 12
    assert apple.direct_pct == pytest.approx(60.0)
    assert apple.indirect_pct == pytest.approx(12.0)
    msft = by_key[("issuer", "594918")]
    assert msft.indirect_pct == pytest.approx(8.0)
    assert by_key[("asset_class", "EC")].direct_pct == pytest.approx(60.0)

    # agregados: staleness = report mais antigo entre os fundos usados
    assert aggregates.oldest_report_date == dt.date(2025, 9, 30)
    assert aggregates.expanded_weight_pct == pytest.approx(80.0)
    assert aggregates.sum_pct_total == pytest.approx(80.0)  # 0.8×100


def test_consolidate_portfolio_empty_is_explicit() -> None:
    rows, aggregates = lt.consolidate_portfolio([])
    assert rows == []
    assert aggregates.expanded_weight_pct == 0.0
    assert aggregates.oldest_report_date is None


# ---------------------------------------------------------------------------
# GET /portfolios/{id}/lookthrough
# ---------------------------------------------------------------------------


def _position(ticker: str, quantity: float) -> SimpleNamespace:
    return SimpleNamespace(
        ticker=ticker, quantity=quantity, acq_price=None, basis="reference",
        commission=None, trade_date=None,
    )


@pytest.mark.anyio
async def test_portfolio_lookthrough_consolidates_and_reports_unexpanded(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    portfolio = SimpleNamespace(
        id=7, name="P", cash=1000.0,
        positions=[_position("FUNDX", 100.0), _position("AAPL", 100.0)],
    )

    async def fake_get_portfolio(session, portfolio_id):
        assert portfolio_id == 7
        return portfolio

    async def fake_fund_series_by_ticker(session, tickers):
        return {"FUNDX": "S_A"}

    async def fake_closes(session, tickers):
        return {"AAPL": [(dt.date(2026, 6, 11), 10.0)]}

    async def fake_navs(session, tickers):
        return {"FUNDX": [(dt.date(2026, 6, 11), 30.0)]}

    async def fake_fetch_many(dl, series_ids):
        assert series_ids == ["S_A"]
        return {"S_A": _series_lookthrough("S_A")}

    monkeypatch.setattr(portfolio_crud, "get_portfolio", fake_get_portfolio)
    monkeypatch.setattr(lt, "get_fund_series_by_ticker", fake_fund_series_by_ticker)
    monkeypatch.setattr(portfolio_crud, "select_last_two_closes", fake_closes)
    monkeypatch.setattr(portfolio_crud, "select_last_two_navs", fake_navs)
    monkeypatch.setattr(lt, "fetch_many_lookthroughs", fake_fetch_many)

    async with _client() as client:
        resp = await client.get("/portfolios/7/lookthrough")
    assert resp.status_code == 200
    body = resp.json()

    # FUNDX: 100×30=3000 ; AAPL: 100×10=1000 ; cash 1000 → total 5000
    # peso FUNDX 60%, AAPL 20%, cash 20%
    assert body["total_value"] == pytest.approx(5000.0)
    assert body["expanded_weight_pct"] == pytest.approx(60.0)
    assert body["cash_weight_pct"] == pytest.approx(20.0)
    unexpanded = body["unexpanded"]
    assert len(unexpanded) == 1
    assert unexpanded[0]["ticker"] == "AAPL"
    assert unexpanded[0]["weight_pct"] == pytest.approx(20.0)

    issuers = {r["key"]: r for r in body["dimensions"]["issuer"]}
    # Apple via FUNDX: 0.6×(50+30) = 48
    assert issuers["037833"]["total_pct"] == pytest.approx(48.0)
    assert body["oldest_report_date"] == "2025-12-31"
    assert body["n_funds_expanded"] == 1


@pytest.mark.anyio
async def test_portfolio_lookthrough_unknown_portfolio_404(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fake_get_portfolio(session, portfolio_id):
        return None

    monkeypatch.setattr(portfolio_crud, "get_portfolio", fake_get_portfolio)
    async with _client() as client:
        resp = await client.get("/portfolios/99/lookthrough")
    assert resp.status_code == 404


@pytest.mark.anyio
async def test_portfolio_lookthrough_fund_without_materialization_is_unexpanded(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    portfolio = SimpleNamespace(
        id=7, name="P", cash=0.0, positions=[_position("FUNDX", 100.0)],
    )

    async def fake_get_portfolio(session, portfolio_id):
        return portfolio

    async def fake_fund_series_by_ticker(session, tickers):
        return {"FUNDX": "S_A"}

    async def fake_navs(session, tickers):
        return {"FUNDX": [(dt.date(2026, 6, 11), 30.0)]}

    async def fake_closes(session, tickers):
        return {}

    async def fake_fetch_many(dl, series_ids):
        return {}  # nada materializado

    monkeypatch.setattr(portfolio_crud, "get_portfolio", fake_get_portfolio)
    monkeypatch.setattr(lt, "get_fund_series_by_ticker", fake_fund_series_by_ticker)
    monkeypatch.setattr(portfolio_crud, "select_last_two_closes", fake_closes)
    monkeypatch.setattr(portfolio_crud, "select_last_two_navs", fake_navs)
    monkeypatch.setattr(lt, "fetch_many_lookthroughs", fake_fetch_many)

    async with _client() as client:
        resp = await client.get("/portfolios/7/lookthrough")
    assert resp.status_code == 200
    body = resp.json()
    assert body["expanded_weight_pct"] == 0.0
    assert body["unexpanded"][0]["ticker"] == "FUNDX"
    assert body["unexpanded"][0]["reason"] == "not_materialized"
    assert body["dimensions"]["issuer"] == []


@pytest.mark.anyio
async def test_portfolio_lookthrough_missing_price_is_loud(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    portfolio = SimpleNamespace(
        id=7, name="P", cash=0.0, positions=[_position("GHOST", 1.0)],
    )

    async def fake_get_portfolio(session, portfolio_id):
        return portfolio

    async def fake_fund_series_by_ticker(session, tickers):
        return {}

    async def fake_empty(session, tickers):
        return {}

    monkeypatch.setattr(portfolio_crud, "get_portfolio", fake_get_portfolio)
    monkeypatch.setattr(lt, "get_fund_series_by_ticker", fake_fund_series_by_ticker)
    monkeypatch.setattr(portfolio_crud, "select_last_two_closes", fake_empty)
    monkeypatch.setattr(portfolio_crud, "select_last_two_navs", fake_empty)

    async with _client() as client:
        resp = await client.get("/portfolios/7/lookthrough")
    assert resp.status_code == 409
    assert "GHOST" in resp.json()["detail"]
