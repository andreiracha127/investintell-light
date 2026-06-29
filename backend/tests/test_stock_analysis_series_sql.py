
import numpy as np
import pandas as pd
import pytest

from app.analytics.rolling import rolling_beta
from app.services import series_sql, stock_analysis


@pytest.mark.asyncio
async def test_rolling_beta_sql_matches_pandas():
    rng = np.random.default_rng(11)
    dates = pd.bdate_range("2025-01-01", periods=140)
    a = pd.Series(rng.normal(0, 0.01, len(dates)), index=dates)
    b = pd.Series(rng.normal(0, 0.01, len(dates)), index=dates)
    legacy = rolling_beta(a, b, 63).dropna()
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

    beta, _ = await series_sql.rolling_beta_corr_points(
        _S(), ticker="SPY", benchmark="QQQ", window=63,
        start=dates[0].date(), end=dates[-1].date(),
    )
    assert len(beta) == len(legacy)
    for (_d, v), (_idx, lv) in zip(beta, legacy.items(), strict=False):
        assert abs(v - float(lv)) < 1e-10


def test_stock_analysis_has_sql_assembler():
    assert hasattr(stock_analysis, "assemble_analysis_sql")
