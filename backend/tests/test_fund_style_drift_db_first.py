# backend/tests/test_fund_style_drift_db_first.py
import datetime as dt
import uuid

import pytest

from app.services import fund_dossier_tier_b as svc

_IID = uuid.uuid4()
_Q1 = dt.date(2026, 1, 31)
_Q2 = dt.date(2025, 10, 31)


class _Result:
    def __init__(self, rows): self._rows = rows
    def mappings(self): return self
    def all(self): return self._rows


class _FakeFund:
    instrument_id = _IID
    series_id = "S000001"
    name = "Test Fund"
    ticker = "TST"


class _FakeSession:
    """Datalake-side fake; routes by marker in the stringified query."""
    def __init__(self, *, mv_rows=None, legacy_rows=None):
        self._mv_rows = mv_rows or []
        self._legacy_rows = legacy_rows or []
        self.executed = []
        self.pandas_used = False

    async def execute(self, query, params=None):
        text = str(query)
        self.executed.append(text)
        if "fund_style_drift_mv" in text:
            return _Result([dict(r) for r in self._mv_rows])
        return _Result([dict(r) for r in self._legacy_rows])


@pytest.fixture(autouse=True)
def _stub_fund(monkeypatch):
    async def _fund(_session, _iid):
        return _FakeFund()
    monkeypatch.setattr(svc, "_fund_or_none", _fund)


@pytest.mark.asyncio
async def test_db_first_path_reshapes_periods():
    # MV query returns ORDER BY report_date ASC (the fake echoes row order,
    # so the rows are supplied already ASC-sorted, as Postgres would return).
    datalake = _FakeSession(mv_rows=[
        {"report_date": _Q2, "sector": "Technology", "weight": 35.0},
        {"report_date": _Q1, "sector": "Technology", "weight": 40.0},
        {"report_date": _Q1, "sector": "Health Care", "weight": 10.0},
    ])
    out = await svc.fetch_fund_style_drift(
        object(), datalake, _IID, quarters=40, use_db_first=True
    )
    assert [p.report_date for p in out.periods] == [_Q2, _Q1]  # ASC, newest last
    q1 = next(p for p in out.periods if p.report_date == _Q1)
    assert {s.sector: s.weight for s in q1.sectors} == {"Technology": 0.40, "Health Care": 0.10}
    assert any("fund_style_drift_mv" in q for q in datalake.executed)


@pytest.mark.asyncio
async def test_db_first_empty_falls_to_empty_state():
    datalake = _FakeSession(mv_rows=[])
    out = await svc.fetch_fund_style_drift(
        object(), datalake, _IID, quarters=40, use_db_first=True
    )
    assert out.periods == []
    assert out.empty_state is not None


@pytest.mark.asyncio
async def test_flag_off_uses_legacy(monkeypatch):
    called = {"legacy": False}
    async def _legacy(_session, _datalake, _iid, *, quarters):
        called["legacy"] = True
        from app.schemas.fund_analysis import FundStyleDriftResponse
        return FundStyleDriftResponse(instrument_id=_IID, series_id="S000001", periods=[])
    monkeypatch.setattr(svc, "_fetch_fund_style_drift_legacy", _legacy)
    out = await svc.fetch_fund_style_drift(
        object(), _FakeSession(), _IID, quarters=40, use_db_first=False
    )
    assert called["legacy"] is True
    assert out.periods == []
