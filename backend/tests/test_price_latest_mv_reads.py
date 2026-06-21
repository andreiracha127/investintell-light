# backend/tests/test_price_latest_mv_reads.py
import datetime as dt

import pytest

from app.services import portfolio_crud

_LAST = dt.date(2026, 6, 18)
_PREV = dt.date(2026, 6, 17)


class _Result:
    def __init__(self, rows): self._rows = rows
    def all(self): return self._rows


class _FakeSession:
    """Roteia execute() por marcador embutido na query stringificada."""
    def __init__(self, *, mv_rows=None, legacy_rows=None):
        self._mv_rows = mv_rows or []
        self._legacy_rows = legacy_rows or []
        self.executed = []

    async def execute(self, query):
        text = str(query)
        self.executed.append(text)
        if "price_latest_mv" in text:
            return _Result(self._mv_rows)
        return _Result(self._legacy_rows)


@pytest.mark.asyncio
async def test_mv_path_reshapes_rows_newest_first():
    # MV row: (ticker, as_of, last_close, prev_date, prev_close)
    session = _FakeSession(mv_rows=[("AAPL", _LAST, 110.0, _PREV, 105.0)])
    out = await portfolio_crud.select_last_two_closes(session, ["AAPL"], use_mv=True)
    assert out == {"AAPL": [(_LAST, 110.0), (_PREV, 105.0)]}


@pytest.mark.asyncio
async def test_mv_path_single_point_has_no_prev():
    session = _FakeSession(mv_rows=[("AAPL", _LAST, 110.0, None, None)])
    out = await portfolio_crud.select_last_two_closes(session, ["AAPL"], use_mv=True)
    assert out == {"AAPL": [(_LAST, 110.0)]}


@pytest.mark.asyncio
async def test_mv_path_falls_back_to_base_for_missing_ticker():
    # MSFT ausente do MV → cai p/ tabela base (legacy rows: ticker, date, close).
    session = _FakeSession(
        mv_rows=[("AAPL", _LAST, 110.0, _PREV, 105.0)],
        legacy_rows=[("MSFT", _LAST, 420.0), ("MSFT", _PREV, 410.0)],
    )
    out = await portfolio_crud.select_last_two_closes(
        session, ["AAPL", "MSFT"], use_mv=True
    )
    assert out["AAPL"] == [(_LAST, 110.0), (_PREV, 105.0)]
    assert out["MSFT"] == [(_LAST, 420.0), (_PREV, 410.0)]
    assert any("eod_prices" in q or "price" in q for q in session.executed)


@pytest.mark.asyncio
async def test_flag_off_uses_legacy_only():
    session = _FakeSession(legacy_rows=[("AAPL", _LAST, 110.0), ("AAPL", _PREV, 105.0)])
    out = await portfolio_crud.select_last_two_closes(session, ["AAPL"], use_mv=False)
    assert out == {"AAPL": [(_LAST, 110.0), (_PREV, 105.0)]}
    assert all("price_latest_mv" not in q for q in session.executed)
