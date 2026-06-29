import uuid

import numpy as np
import pandas as pd
import pytest

from app.services import fund_dossier_tier_b as tb
from app.services import series_sql


@pytest.mark.asyncio
async def test_drawdown_series_sql_matches_max_drawdown_series():
    rng = np.random.default_rng(3)
    dates = pd.bdate_range("2025-01-01", periods=80)
    nav = pd.Series(100 * (1 + rng.normal(0, 0.01, len(dates))).cumprod(), index=dates)
    legacy = tb._max_drawdown_series(nav)  # nav/cummax - 1.0
    fn_rows = [(idx.date(), float(v)) for idx, v in legacy.items()]

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
    assert len(pts) == len(legacy)
    for (_d, v), (_idx, lv) in zip(pts, legacy.items(), strict=False):
        assert abs(v - float(lv)) < 1e-10


def test_entity_analytics_has_sql_assembler():
    assert hasattr(tb, "assemble_entity_analytics_sql")
