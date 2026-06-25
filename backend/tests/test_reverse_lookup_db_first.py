import datetime as dt

import pytest

from app.services import fund_dossier_tier_b as tier_b

_PERIOD = dt.date(2026, 3, 31)


class _Result:
    def __init__(self, rows): self._rows = rows
    def mappings(self): return self
    def all(self): return self._rows


class _FakeDatalake:
    def __init__(self, *, mv_rows=None, legacy_rows=None):
        self._mv_rows = mv_rows or []
        self._legacy_rows = legacy_rows or []
        self.executed = []

    async def execute(self, query, params=None):
        text = str(query)
        self.executed.append(text)
        if "holding_reverse_lookup_mv" in text:
            return _Result(self._mv_rows)
        return _Result(self._legacy_rows)


def _inst_row(**over):
    base = {
        "cik": "0001067983", "manager_name": "Berkshire Hathaway Inc",
        "period": _PERIOD, "report_date": _PERIOD, "name": "Apple Inc",
        "value_usd": 150_000_000_000.0, "shares": 900_000_000.0,
    }
    base.update(over)
    return base


@pytest.mark.asyncio
async def test_b3_mv_path_reads_institutions_from_mv(monkeypatch):
    async def _fake_fund_side(session, cusip):
        return []
    monkeypatch.setattr(tier_b, "_fund_exposures_for_cusip", _fake_fund_side)

    datalake = _FakeDatalake(mv_rows=[_inst_row()])
    resp = await tier_b.fetch_holding_reverse_lookup(
        object(), datalake, "037833100", use_db_first=True
    )
    assert resp.cusip == "037833100"
    assert len(resp.institutions) == 1
    assert resp.institutions[0].manager_name == "Berkshire Hathaway Inc"
    assert resp.security_name == "Apple Inc"
    assert any("holding_reverse_lookup_mv" in q for q in datalake.executed)
    # MV path NÃO toca a hypertable crua.
    assert all("FROM sec_13f_holdings h" not in q for q in datalake.executed)


@pytest.mark.asyncio
async def test_b3_mv_empty_sets_empty_state(monkeypatch):
    async def _fake_fund_side(session, cusip):
        return []
    monkeypatch.setattr(tier_b, "_fund_exposures_for_cusip", _fake_fund_side)

    datalake = _FakeDatalake(mv_rows=[])
    resp = await tier_b.fetch_holding_reverse_lookup(
        object(), datalake, "037833100", use_db_first=True
    )
    assert resp.institutions == []
    assert resp.empty_state is not None


@pytest.mark.asyncio
async def test_b3_flag_off_uses_legacy_sql(monkeypatch):
    async def _fake_fund_side(session, cusip):
        return []
    monkeypatch.setattr(tier_b, "_fund_exposures_for_cusip", _fake_fund_side)

    datalake = _FakeDatalake(legacy_rows=[_inst_row()])
    resp = await tier_b.fetch_holding_reverse_lookup(
        object(), datalake, "037833100", use_db_first=False
    )
    assert len(resp.institutions) == 1
    assert all("holding_reverse_lookup_mv" not in q for q in datalake.executed)
