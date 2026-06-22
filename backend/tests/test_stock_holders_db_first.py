import datetime as dt
import uuid

import pytest

from app.services import stock_holders

_PERIOD = dt.date(2026, 3, 31)
_ENTRY = dt.date(2024, 6, 30)


class _Result:
    def __init__(self, rows): self._rows = rows
    def mappings(self): return self
    def all(self): return self._rows


class _FakeSession:
    """Roteia execute() por marcador na query stringificada (MV vs legado)."""
    def __init__(self, *, mv_rows=None, legacy_rows=None):
        self._mv_rows = mv_rows or []
        self._legacy_rows = legacy_rows or []
        self.executed = []

    async def execute(self, query, params=None):
        text = str(query)
        self.executed.append(text)
        if "stock_institutional_holders_mv" in text or "stock_fund_holders_mv" in text:
            return _Result(self._mv_rows)
        return _Result(self._legacy_rows)


def _b1_row(**over):
    base = {
        "ticker": "AAPL", "cik": "0000320193", "manager_name": "Vanguard Group Inc",
        "report_date": _PERIOD, "cusip": "037833100", "issuer_name": "Apple Inc",
        "shares": 1_000_000.0, "market_value": 200_000_000.0, "entry_date": _ENTRY,
        "entry_price": 100.0, "current_price": 110.0, "shares_outstanding": 15_000_000_000.0,
    }
    base.update(over)
    return base


@pytest.mark.asyncio
async def test_b1_mv_path_reshapes_and_computes_pct_and_return():
    session = _FakeSession(mv_rows=[_b1_row()])
    resp = await stock_holders.fetch_stock_holders(session, "AAPL", use_db_first=True)
    assert resp.ticker == "AAPL"
    assert resp.holder_count == 1
    h = resp.holders[0]
    assert h.manager_name == "Vanguard Group Inc"
    assert h.pct_outstanding == pytest.approx(1_000_000.0 / 15_000_000_000.0)
    assert h.position_return == pytest.approx(110.0 / 100.0 - 1.0)
    # MV path NÃO toca a hypertable crua.
    assert any("stock_institutional_holders_mv" in q for q in session.executed)
    assert all("FROM sec_13f_holdings h" not in q for q in session.executed)


@pytest.mark.asyncio
async def test_b1_mv_empty_returns_empty_state():
    session = _FakeSession(mv_rows=[])
    resp = await stock_holders.fetch_stock_holders(session, "ZZZZ", use_db_first=True)
    assert resp.empty_state is not None
    assert resp.holders == []


@pytest.mark.asyncio
async def test_b1_flag_off_uses_legacy_sql():
    session = _FakeSession(legacy_rows=[_b1_row()])
    resp = await stock_holders.fetch_stock_holders(session, "AAPL", use_db_first=False)
    assert resp.holder_count == 1
    assert all("stock_institutional_holders_mv" not in q for q in session.executed)


def _b2_row(**over):
    base = {
        "ticker": "AAPL", "registrant_cik": "0000102909", "family": "Vanguard",
        "series_id": "S000002277", "fund_name": "Vanguard 500 Index Fund",
        "instrument_id": uuid.uuid4(), "issuer_name": "Apple Inc",
        "quantity": 500.0, "market_value": 1_000_000.0, "pct_of_nav": 6.5,
        "pct_nav_q1": 6.4, "pct_nav_q2": 6.3, "pct_nav_q3": 6.2,
        "report_date": _PERIOD, "cusip": "037833100",
    }
    base.update(over)
    return base


@pytest.mark.asyncio
async def test_b2_mv_path_groups_family_to_funds():
    rows = [
        _b2_row(series_id="S1", fund_name="Fund A", market_value=1_000_000.0),
        _b2_row(series_id="S2", fund_name="Fund B", market_value=2_000_000.0),
    ]
    session = _FakeSession(mv_rows=rows)
    resp = await stock_holders.fetch_stock_fund_holders(session, "AAPL", use_db_first=True)
    assert resp.family_count == 1
    assert resp.fund_count == 2
    fam = resp.families[0]
    assert fam.family == "Vanguard"
    assert fam.fund_count == 2
    assert fam.market_value == pytest.approx(3_000_000.0)
    assert any("stock_fund_holders_mv" in q for q in session.executed)
    assert all("FROM nport_holdings_history" not in q for q in session.executed)


@pytest.mark.asyncio
async def test_b2_flag_off_uses_legacy_sql():
    session = _FakeSession(legacy_rows=[_b2_row()])
    resp = await stock_holders.fetch_stock_fund_holders(session, "AAPL", use_db_first=False)
    assert resp.fund_count == 1
    assert all("stock_fund_holders_mv" not in q for q in session.executed)


@pytest.mark.asyncio
async def test_b1_parity_mv_vs_legacy_same_payload():
    row = _b1_row()
    mv = await stock_holders.fetch_stock_holders(
        _FakeSession(mv_rows=[row]), "AAPL", use_db_first=True
    )
    legacy = await stock_holders.fetch_stock_holders(
        _FakeSession(legacy_rows=[row]), "AAPL", use_db_first=False
    )
    assert mv.model_dump() == legacy.model_dump()
