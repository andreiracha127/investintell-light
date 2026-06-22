# backend/tests/test_active_share_db_first.py
import datetime as dt
import uuid

import pytest

from app.services import fund_dossier_tier_b as svc

_IID = uuid.uuid4()
_BENCH_IID = uuid.uuid4()
_AS_OF = dt.date(2026, 1, 31)


class _Result:
    def __init__(self, value=None):
        self._value = value

    def scalar_one_or_none(self):
        return self._value

    def scalar(self):
        return self._value


class _FakeFund:
    instrument_id = _IID
    series_id = "S000001"
    name = "Test Fund"


class _FakeRiskLatest:
    """Shape of a fund_risk_latest_mv row (FundRiskLatest)."""

    def __init__(self, *, covered=True):
        self.instrument_id = _IID
        if covered:
            self.active_share_normalized = 0.42
            self.overlap_normalized = 0.58
            self.n_fund_holdings = 120
            self.n_benchmark_holdings = 500
            self.n_common_holdings = 90
            self.active_share_fund_report_date = _AS_OF
            self.active_share_benchmark_series_id = "S000999"
            self.active_share_benchmark_instrument_id = _BENCH_IID
        else:
            self.active_share_normalized = None
            self.overlap_normalized = None
            self.n_fund_holdings = None
            self.n_benchmark_holdings = None
            self.n_common_holdings = None
            self.active_share_fund_report_date = None
            self.active_share_benchmark_series_id = None
            self.active_share_benchmark_instrument_id = None


class _FakeSession:
    """Fakes the app-DB session: ``get`` for FundRiskLatest, ``execute`` for the
    small benchmark-name resolution read."""

    def __init__(self, *, risk_row=None, bench_name=None):
        self._risk_row = risk_row
        self._bench_name = bench_name
        self.executed = []

    async def get(self, model, pk):
        return self._risk_row

    async def execute(self, query, params=None):
        self.executed.append(str(query))
        return _Result(self._bench_name)


@pytest.fixture(autouse=True)
def _stub_fund(monkeypatch):
    async def _fund(_session, _iid):
        return _FakeFund()

    monkeypatch.setattr(svc, "_fund_or_none", _fund)


@pytest.mark.asyncio
async def test_db_first_reads_active_share_from_risk_latest_mv():
    session = _FakeSession(
        risk_row=_FakeRiskLatest(covered=True), bench_name="S&P 500 Index"
    )
    out = await svc.fetch_fund_active_share(session, object(), _IID, use_db_first=True)

    assert out.active_share == 0.42
    assert out.overlap == 0.58
    assert out.benchmark_series_id == "S000999"
    assert out.n_portfolio_positions == 120
    assert out.n_benchmark_positions == 500
    assert out.n_common_positions == 90
    assert out.as_of_date == _AS_OF
    assert out.benchmark_name == "S&P 500 Index"
    assert out.empty_state is None
    assert not hasattr(out, "benchmark_id")  # campo removido do schema


@pytest.mark.asyncio
async def test_db_first_null_active_share_yields_empty_state():
    session = _FakeSession(risk_row=_FakeRiskLatest(covered=False))
    out = await svc.fetch_fund_active_share(session, object(), _IID, use_db_first=True)

    assert out.empty_state is not None
    assert out.empty_state.source == "fund_risk_latest_mv"
    assert out.active_share is None


@pytest.mark.asyncio
async def test_db_first_no_risk_row_yields_empty_state():
    session = _FakeSession(risk_row=None)
    out = await svc.fetch_fund_active_share(session, object(), _IID, use_db_first=True)

    assert out.empty_state is not None
    assert out.empty_state.source == "fund_risk_latest_mv"
    assert out.active_share is None


@pytest.mark.asyncio
async def test_db_first_benchmark_name_falls_back_to_series_id():
    # No funds_list_mv name and no proxy ticker → benchmark_name is the series_id.
    session = _FakeSession(risk_row=_FakeRiskLatest(covered=True), bench_name=None)
    out = await svc.fetch_fund_active_share(session, object(), _IID, use_db_first=True)

    assert out.benchmark_name == "S000999"


@pytest.mark.asyncio
async def test_flag_off_falls_back_to_legacy(monkeypatch):
    called = {}

    async def _legacy(session, datalake, iid, *, benchmark_id):
        called["benchmark_id"] = benchmark_id
        called["hit"] = True
        return svc.FundActiveShareResponse(instrument_id=iid)

    monkeypatch.setattr(svc, "_fetch_fund_active_share_legacy", _legacy)

    out = await svc.fetch_fund_active_share(
        _FakeSession(), object(), _IID, use_db_first=False
    )

    assert called["hit"] is True
    assert called["benchmark_id"] is None
    assert out.instrument_id == _IID
