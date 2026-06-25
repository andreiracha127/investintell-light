import datetime as dt
import uuid

import pytest

from app.services import portfolio_crud

_LAST = dt.date(2026, 6, 18)
_PREV = dt.date(2026, 6, 17)
_IID = uuid.uuid4()


class _Result:
    def __init__(self, rows): self._rows = rows
    def all(self): return self._rows


class _FakeSession:
    def __init__(self, *, mv_rows=None, legacy_rows=None):
        self._mv_rows = mv_rows or []
        self._legacy_rows = legacy_rows or []
        self.executed = []

    async def execute(self, query):
        text = str(query)
        self.executed.append(text)
        if "nav_latest_mv" in text:
            return _Result(self._mv_rows)
        return _Result(self._legacy_rows)


@pytest.mark.asyncio
async def test_nav_mv_path_reshapes_newest_first(monkeypatch):
    async def _fake_resolve(session, tickers):
        return {"VBIAX": _IID}
    monkeypatch.setattr(portfolio_crud, "_fund_instrument_by_ticker", _fake_resolve)

    # MV row: (instrument_id, as_of, last_nav, prev_date, prev_nav)
    session = _FakeSession(mv_rows=[(_IID, _LAST, 50.0, _PREV, 49.0)])
    out = await portfolio_crud.select_last_two_navs(session, ["VBIAX"], use_mv=True)
    assert out == {"VBIAX": [(_LAST, 50.0), (_PREV, 49.0)]}


@pytest.mark.asyncio
async def test_nav_mv_path_falls_back_for_missing_instrument(monkeypatch):
    async def _fake_resolve(session, tickers):
        return {"VBIAX": _IID}
    monkeypatch.setattr(portfolio_crud, "_fund_instrument_by_ticker", _fake_resolve)

    # MV vazio → cai p/ legado (legacy_rows: instrument_id, nav_date, nav)
    session = _FakeSession(mv_rows=[], legacy_rows=[(_IID, _LAST, 50.0), (_IID, _PREV, 49.0)])
    out = await portfolio_crud.select_last_two_navs(session, ["VBIAX"], use_mv=True)
    assert out == {"VBIAX": [(_LAST, 50.0), (_PREV, 49.0)]}
