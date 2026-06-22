# backend/tests/test_holdings_top_db_first.py
import datetime as dt
import uuid

import pytest

from app.services import fund_analysis as svc

_IID = uuid.uuid4()
_RD = dt.date(2026, 1, 31)


class _Result:
    def __init__(self, rows): self._rows = rows
    def mappings(self): return self
    def all(self): return self._rows


class _FakeFund:
    instrument_id = _IID
    series_id = "S000001"


class _FakeSession:
    """App-DB side fake: session.get(Fund, id) → fund; execute() → mv rows."""
    def __init__(self, *, mv_rows=None):
        self._mv_rows = mv_rows or []
        self.executed = []

    async def get(self, _model, _iid):
        return _FakeFund()

    async def execute(self, query, params=None):
        self.executed.append(str(query))
        return _Result([dict(r) for r in self._mv_rows])


@pytest.mark.asyncio
async def test_db_first_reads_top_holdings_from_mv(monkeypatch):
    async def _breakdown(_datalake, _series):
        return []  # força fallback de breakdown só se necessário; aqui basta lista vazia
    monkeypatch.setattr(svc, "_sector_breakdown_from_lookthrough", _breakdown)
    monkeypatch.setattr(svc, "_sector_breakdown_from_holdings", lambda _h: [])

    session = _FakeSession(mv_rows=[
        {"series_id": "S000001", "report_date": _RD, "rank": 1,
         "issuer_name": "Apple Inc", "cusip": "037833100", "isin": None,
         "asset_class": "EC", "sector": None, "gics_sector": "Information Technology",
         "market_value": 1000.0, "pct_of_nav": 5.0},
    ])
    out = await svc.fetch_fund_holdings_top(session, _FakeSession(), _IID, limit=25, use_db_first=True)
    assert out.report_date == _RD
    assert out.top_holdings[0].issuer_name == "Apple Inc"
    assert out.top_holdings[0].gics_sector == "Information Technology"
    assert out.top_holdings[0].pct_of_nav == 5.0
    assert any("fund_top_holdings_mv" in q for q in session.executed)


@pytest.mark.asyncio
async def test_flag_off_uses_legacy(monkeypatch):
    called = {"legacy": False}
    async def _legacy(_session, _datalake, _iid, *, limit):
        called["legacy"] = True
        from app.schemas.fund_analysis import FundHoldingsTopResponse
        return FundHoldingsTopResponse(
            instrument_id=_IID, series_id="S000001", report_date=None,
            top_holdings=[], sector_breakdown=[], pct_of_nav_total=None,
        )
    monkeypatch.setattr(svc, "_fetch_fund_holdings_top_legacy", _legacy)
    out = await svc.fetch_fund_holdings_top(_FakeSession(), _FakeSession(), _IID, limit=25, use_db_first=False)
    assert called["legacy"] is True
    assert out.top_holdings == []
