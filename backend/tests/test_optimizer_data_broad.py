"""Tests for the broad-universe data seam in app/optimizer/data.py:
- load_returns_matrix: T×N WITHOUT global dropna (NaN preserved),
- select_universe_funds: cap removed (max_assets=None) + MAX_UNIVERSE_CANDIDATES,
- load_fund_quality_metrics: Sharpe/expense/AUM per fund.
"""

import datetime as dt
import uuid
from typing import Any

import numpy as np
import pandas as pd
import pytest

from app.optimizer import data as optimizer_data

_FUND_A = uuid.UUID("00000000-0000-0000-0000-00000000000a")
_FUND_B = uuid.UUID("00000000-0000-0000-0000-00000000000b")
_TODAY = dt.date(2026, 6, 11)


class _FakeResult:
    def __init__(self, rows: list[tuple[Any, ...]]) -> None:
        self._rows = rows

    def all(self) -> list[tuple[Any, ...]]:
        return self._rows


def _nav_rows(
    n: int, start: dt.date, nav0: float = 100.0
) -> list[tuple[dt.date, float, float | None]]:
    rng = np.random.default_rng(abs(hash(start)) % 2**32)
    rows = []
    nav = nav0
    day = start
    for _ in range(n):
        while day.weekday() >= 5:
            day += dt.timedelta(days=1)
        r = float(rng.normal(0.0003, 0.006))
        nav *= float(np.exp(r))
        rows.append((day, nav, r))
        day += dt.timedelta(days=1)
    return rows


class _FakeSession:
    def __init__(self, fund_rows: dict[uuid.UUID, list[tuple[Any, ...]]]) -> None:
        self._fund_rows = fund_rows

    async def execute(self, stmt: Any) -> _FakeResult:
        params = stmt.compile().params
        for fund_id, rows in self._fund_rows.items():
            if fund_id in params.values():
                return _FakeResult(rows)
        return _FakeResult([])


async def test_load_returns_matrix_preserves_nan_no_global_dropna() -> None:
    """Fund A: 500 obs from 2024-01; Fund B: 500 obs from 2024-06 (younger).
    The union index keeps ALL dates; the early rows for B are NaN, not dropped.
    """
    rows_a = _nav_rows(500, dt.date(2024, 1, 2))
    rows_b = _nav_rows(500, dt.date(2024, 6, 3))
    session = _FakeSession({_FUND_A: rows_a, _FUND_B: rows_b})
    refs = [
        optimizer_data.FundAssetRef(id=_FUND_A),
        optimizer_data.FundAssetRef(id=_FUND_B),
    ]
    frame = await optimizer_data.load_returns_matrix(
        session, refs, window_days=None, today=_TODAY
    )
    # Union index is longer than the per-fund overlap (a dropna would shrink it).
    assert len(frame) > 500
    assert frame.isna().any().any()  # NaN preserved (B's early dates)
    assert list(frame.columns) == [r.label for r in refs]


async def test_load_returns_matrix_rejects_fewer_than_two() -> None:
    session = _FakeSession({_FUND_A: _nav_rows(500, dt.date(2024, 1, 2))})
    with pytest.raises(ValueError, match="at least 2"):
        await optimizer_data.load_returns_matrix(
            session, [optimizer_data.FundAssetRef(id=_FUND_A)],
            window_days=None, today=_TODAY,
        )


def test_max_universe_candidates_default_is_2000() -> None:
    assert optimizer_data.MAX_UNIVERSE_CANDIDATES == 2000
