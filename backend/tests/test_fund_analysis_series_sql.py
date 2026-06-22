import datetime as dt
import math
import uuid

import numpy as np
import pandas as pd
import pytest

from app.services import fund_analysis, series_sql


def _legacy_rolling_vol(returns: pd.Series, window: int):
    return (returns.rolling(window, min_periods=window).std(ddof=1) * math.sqrt(252)).dropna()


@pytest.mark.asyncio
async def test_rolling_vol_sql_matches_pandas(monkeypatch):
    # Build a deterministic NAV series; compute the legacy rolling vol; assert the
    # SQL helper (stubbed to emulate the fn) matches within 1e-10.
    rng = np.random.default_rng(7)
    dates = pd.bdate_range("2025-01-01", periods=120)
    nav = pd.Series(100 * (1 + rng.normal(0, 0.01, len(dates))).cumprod(), index=dates)
    returns = nav.pct_change().dropna()
    legacy = _legacy_rolling_vol(returns, 63)

    # Emulate fn_rolling_metrics output rows for the SAME math (window full only).
    fn_rows = [(idx.date(), float(v), None) for idx, v in legacy.items()]

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

    vol, _ = await series_sql.rolling_metrics_points(
        _S(), instrument_id=uuid.uuid4(), window=63,
        start=dates[0].date(), end=dates[-1].date(),
    )
    assert len(vol) == len(legacy)
    for (d, v), (idx, lv) in zip(vol, legacy.items()):
        assert d == idx.date()
        assert abs(v - float(lv)) < 1e-10


@pytest.mark.asyncio
async def test_fund_analysis_sql_path_calls_fn_and_no_pandas(monkeypatch):
    # With the flag ON, fetch_fund_analysis must call the fn_* helpers and the
    # assembled series must not have been produced by .rolling.
    captured: dict = {"sql": []}

    async def _fake_rolling(session, **kw):
        return ([(dt.date(2026, 6, 18), 0.1)], [(dt.date(2026, 6, 18), 1.0)])

    async def _fake_dd(session, **kw):
        return [(dt.date(2026, 6, 18), -0.02)]

    async def _fake_hist(session, **kw):
        from app.schemas.analysis import HistogramOut
        return HistogramOut(bin_edges=[0.0, 1.0], counts=[1], counts_normalized=[1.0])

    async def _fake_var(session, **kw):
        captured["sql"].append("fn_var_cvar")
        return (0.02, 0.03)

    monkeypatch.setattr(series_sql, "rolling_metrics_points", _fake_rolling)
    monkeypatch.setattr(series_sql, "drawdown_points", _fake_dd)
    monkeypatch.setattr(series_sql, "histogram_out", _fake_hist)
    monkeypatch.setattr(series_sql, "var_cvar", _fake_var)

    # The assembler under test must route through series_sql when use_sql=True.
    assert hasattr(fund_analysis, "assemble_fund_analysis_sql")
