import datetime as dt
import uuid

import pytest

from app.services import series_sql

_D1 = dt.date(2026, 6, 16)
_D2 = dt.date(2026, 6, 17)
_D3 = dt.date(2026, 6, 18)


class _Result:
    def __init__(self, rows):
        self._rows = rows

    def all(self):
        return self._rows

    def one(self):
        return self._rows[0]


class _FakeSession:
    def __init__(self, by_fn):
        self._by_fn = by_fn
        self.executed = []

    async def execute(self, query, params=None):
        text = str(query)
        self.executed.append(text)
        for fn, rows in self._by_fn.items():
            if fn in text:
                return _Result(rows)
        return _Result([])


@pytest.mark.asyncio
async def test_rolling_metrics_drops_null_rows_and_splits_series():
    # rows: (d, vol, sharpe); a leading NULL (warm-up) row is dropped per series.
    session = _FakeSession({"fn_rolling_metrics": [
        (_D1, None, None),
        (_D2, 0.10, 1.2),
        (_D3, 0.11, None),  # sharpe NULL here -> dropped from sharpe only
    ]})
    vol, sharpe = await series_sql.rolling_metrics_points(
        session, ticker="SPY", window=2, start=_D1, end=_D3
    )
    assert vol == [(_D2, 0.10), (_D3, 0.11)]
    assert sharpe == [(_D2, 1.2)]
    assert any("fn_rolling_metrics" in q for q in session.executed)


@pytest.mark.asyncio
async def test_drawdown_points_reshape():
    session = _FakeSession({"fn_drawdown": [(_D1, 0.0), (_D2, -0.05), (_D3, -0.02)]})
    pts = await series_sql.drawdown_points(
        session, instrument_id=uuid.uuid4(), start=_D1, end=_D3
    )
    assert pts == [(_D1, 0.0), (_D2, -0.05), (_D3, -0.02)]
    assert any("fn_drawdown" in q for q in session.executed)


@pytest.mark.asyncio
async def test_histogram_out_builds_21_edges_and_normalizes():
    # 3 bins, lo=0.0 hi=0.3: edges 0,0.1,0.2,0.3; counts 2,4,1; max=4.
    session = _FakeSession({"fn_histogram": [
        (1, 0.0, 0.1, 2),
        (2, 0.1, 0.2, 4),
        (3, 0.2, 0.3, 1),
    ]})
    hist = await series_sql.histogram_out(
        session, ticker="SPY", bins=3, start=_D1, end=_D3
    )
    assert hist.bin_edges == [0.0, 0.1, 0.2, 0.3]
    assert hist.counts == [2, 4, 1]
    assert hist.counts_normalized == [0.5, 1.0, 0.25]
    assert any("fn_histogram" in q for q in session.executed)


@pytest.mark.asyncio
async def test_var_cvar_returns_pair():
    session = _FakeSession({"fn_var_cvar": [(0.021, 0.034)]})
    var, cvar = await series_sql.var_cvar(
        session, ticker="SPY", level=0.95, start=_D1, end=_D3
    )
    assert (var, cvar) == (0.021, 0.034)
    assert any("fn_var_cvar" in q for q in session.executed)


def test_slice_strict_and_week_downsample():
    pts = [(dt.date(2026, 6, 15), 1.0), (dt.date(2026, 6, 16), 2.0),
           (dt.date(2026, 6, 19), 3.0), (dt.date(2026, 6, 22), 4.0)]
    assert series_sql.slice_strict(pts, dt.date(2026, 6, 15)) == pts[1:]
    # 16th and 19th are the same ISO week -> keep the 19th (last); 22nd next week.
    wk = series_sql.week_downsample(pts[1:])
    assert wk == [(dt.date(2026, 6, 19), 3.0), (dt.date(2026, 6, 22), 4.0)]
