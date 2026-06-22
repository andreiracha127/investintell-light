# backend/tests/test_active_share_db_first.py
import datetime as dt
import uuid

import pytest

from app.services import fund_dossier_tier_b as svc

_IID = uuid.uuid4()
_AS_OF = dt.date(2026, 1, 31)


class _Result:
    def __init__(self, rows): self._rows = rows
    def mappings(self): return self
    def all(self): return self._rows
    def first(self): return self._rows[0] if self._rows else None


class _FakeFund:
    instrument_id = _IID
    series_id = "S000001"
    name = "Test Fund"


class _FakeSession:
    def __init__(self, *, mv_row=None):
        self._mv_row = mv_row
        self.executed = []

    async def execute(self, query, params=None):
        self.executed.append(str(query))
        return _Result([self._mv_row] if self._mv_row else [])


@pytest.fixture(autouse=True)
def _stub_fund(monkeypatch):
    async def _fund(_session, _iid):
        return _FakeFund()
    monkeypatch.setattr(svc, "_fund_or_none", _fund)


@pytest.mark.asyncio
async def test_db_first_reads_active_share_from_mv():
    row = {
        "series_id": "S000001", "benchmark_series_id": "S000999",
        "benchmark_name": "S&P 500", "active_share": 0.42, "overlap": 0.58,
        "n_portfolio": 120, "n_benchmark": 500, "n_common": 90, "as_of": _AS_OF,
    }
    out = await svc.fetch_fund_active_share(object(), _FakeSession(mv_row=row), _IID, use_db_first=True)
    assert out.active_share == 0.42
    assert out.overlap == 0.58
    assert out.benchmark_series_id == "S000999"
    assert out.n_common_positions == 90
    assert not hasattr(out, "benchmark_id")  # campo removido do schema


@pytest.mark.asyncio
async def test_db_first_no_benchmark_yields_empty_state():
    out = await svc.fetch_fund_active_share(object(), _FakeSession(mv_row=None), _IID, use_db_first=True)
    assert out.empty_state is not None
    assert out.active_share is None
