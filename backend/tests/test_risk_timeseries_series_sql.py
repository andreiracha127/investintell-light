import datetime as dt
import uuid

import numpy as np
import pandas as pd
import pytest

from app.core.config import get_settings
from app.services import fund_dossier_tier_b as tb
from app.services import series_sql


@pytest.mark.asyncio
async def test_risk_timeseries_drawdown_x100_matches_legacy():
    rng = np.random.default_rng(5)
    dates = pd.bdate_range("2025-06-01", periods=260)
    nav = pd.Series(100 * (1 + rng.normal(0, 0.01, len(dates))).cumprod(), index=dates)
    legacy = (tb._max_drawdown_series(nav) * 100.0)
    fn_rows = [(idx.date(), float(v)) for idx, v in tb._max_drawdown_series(nav).items()]

    class _R:
        def __init__(self, rows):
            self._rows = rows

        def all(self):
            return self._rows

    class _S:
        executed = []

        async def execute(self, q, p=None):
            self.executed.append(str(q))
            return _R(fn_rows)

    pts = await series_sql.drawdown_points(
        _S(), instrument_id=uuid.uuid4(), start=dates[0].date(), end=dates[-1].date()
    )
    scaled = [(d, v * 100.0) for d, v in pts]
    assert len(scaled) == len(legacy)
    for (d, v), (idx, lv) in zip(scaled, legacy.items()):
        assert abs(v - float(lv)) < 1e-10


@pytest.mark.asyncio
async def test_flag_on_uses_fn_drawdown_not_pandas(monkeypatch):
    dates = pd.bdate_range("2025-06-01", periods=260)
    nav = pd.Series(100.0 + np.arange(len(dates), dtype=float), index=dates)
    instrument = uuid.uuid4()

    fund = type("F", (), {"instrument_id": instrument, "series_id": "S1", "name": "X"})()

    async def _fake_fund(session, iid):
        return fund

    async def _fake_bounds(session, iid):
        return dates[0].date(), dates[-1].date()

    async def _fake_rows(session, iid, start, end):
        return [(idx.date(), float(v)) for idx, v in nav.items()]

    async def _fake_dd(session, **kw):
        return [(dt.date(2026, 6, 18), -0.02)]

    def _boom(*a, **k):
        raise AssertionError("_max_drawdown_series must not run on the SQL path")

    async def _fake_regimes(datalake, d0, d1):
        return ([], None)

    monkeypatch.setattr(tb, "_fund_or_none", _fake_fund)
    monkeypatch.setattr(tb, "select_nav_date_bounds", _fake_bounds)
    monkeypatch.setattr(tb, "select_nav_rows", _fake_rows)
    monkeypatch.setattr(series_sql, "drawdown_points", _fake_dd)
    monkeypatch.setattr(tb, "_max_drawdown_series", _boom)
    monkeypatch.setattr(tb, "_conditional_volatility", lambda returns: ([], "garch"))
    monkeypatch.setattr(tb, "_regime_bands", _fake_regimes)

    get_settings.cache_clear()
    monkeypatch.setenv("USE_SERIES_DB_FIRST", "true")
    get_settings.cache_clear()

    payload = await tb.fetch_fund_risk_timeseries(
        object(), object(), instrument, from_date=None, to_date=None
    )
    assert payload.drawdown == [(dt.date(2026, 6, 18), -2.0)]

    get_settings.cache_clear()
    monkeypatch.delenv("USE_SERIES_DB_FIRST", raising=False)
    get_settings.cache_clear()
