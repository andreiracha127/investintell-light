# backend/tests/test_institutional_reveal_db_first.py
import datetime as dt
import uuid

import pytest

from app.services import fund_dossier_tier_b as svc

_IID = uuid.uuid4()
_AS_OF = dt.date(2026, 1, 31)


class _Result:
    def __init__(self, rows): self._rows = rows
    def mappings(self): return self
    def first(self): return self._rows[0] if self._rows else None


class _FakeFund:
    instrument_id = _IID
    series_id = "S000001"
    name = "Test Fund"
    ticker = "TST"


class _FakeSession:
    def __init__(self, *, row=None):
        self._row = row; self.executed = []
    async def execute(self, query, params=None):
        self.executed.append(str(query))
        return _Result([self._row] if self._row else [])


@pytest.fixture(autouse=True)
def _stub_fund(monkeypatch):
    async def _fund(_s, _iid): return _FakeFund()
    monkeypatch.setattr(svc, "_fund_or_none", _fund)


@pytest.mark.asyncio
async def test_db_first_reads_payload_from_mv():
    payload = {
        "schema_version": 1,
        "top_holders": [{"cik": "1", "manager_name": "Alpha", "value_usd": 100.0,
                         "shares": 10.0, "holding_count": 1, "period": "2026-03-31",
                         "report_date": "2026-03-31"}],
        "overlap": [{"cusip": "AAA", "name": "Apple", "fund_pct_of_nav": 0.05,
                     "institutional_value_usd": 100.0, "institution_count": 1,
                     "top_managers": ["Alpha"]}],
        "holder_network": {"nodes": [{"id": "series:S000001", "label": "TST", "type": "fund"}],
                           "edges": []},
        "period": "2026-03-31",
    }
    row = {"series_id": "S000001", "as_of": _AS_OF, "schema_version": 1, "payload": payload}
    out = await svc.fetch_fund_institutional_reveal(object(), _FakeSession(row=row), _IID, use_db_first=True)
    assert out.top_holders[0].manager_name == "Alpha"
    assert out.overlap[0].cusip == "AAA"
    assert out.holder_network.nodes[0].type == "fund"


@pytest.mark.asyncio
async def test_db_first_empty_yields_empty_payload():
    out = await svc.fetch_fund_institutional_reveal(object(), _FakeSession(row=None), _IID, use_db_first=True)
    assert out.top_holders == []
    assert out.empty_state is not None


def test_reveal_sql_normalizes_cik_and_falls_back_to_filings():
    """Manager names resolve robustly: pad the CIK to 10 digits on every join
    side (holdings stores it inconsistently) and fall back to the 13F filing's
    manager name before surfacing a raw CIK placeholder."""
    for q in (svc._INSTITUTIONAL_REVEAL_SQL, svc._REVERSE_LOOKUP_SQL):
        # CIK normalized to the 10-digit zero-padded form used by the name tables.
        assert q.count("lpad(h.cik, 10, '0')") >= 3
        # Resolution order: sec_managers → sec_13f_filings → raw placeholder.
        assert "FROM sec_managers m" in q
        assert "FROM sec_13f_filings f" in q
        assert "filing_manager_name" in q
        mgr_pos = q.index("sec_managers m")
        flr_pos = q.index("sec_13f_filings f")
        placeholder_pos = q.index("'CIK ' || lpad(h.cik, 10, '0')")
        # COALESCE lists the placeholder first (in the SELECT), then the two
        # LATERAL sources below it — assert both sources precede neither other's
        # role by checking the managers LATERAL comes before the filings LATERAL.
        assert mgr_pos < flr_pos
        assert placeholder_pos < mgr_pos
