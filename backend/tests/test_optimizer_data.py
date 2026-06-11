"""Unit tests for app/optimizer/data.py with a faked AsyncSession (no DB).

Covers: return_1d preference with log-NAV fallback, date intersection,
the >= 400 common observations guard, unknown assets and duplicates.
"""

import datetime as dt
import uuid
from typing import Any

import numpy as np
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


class _FakeSession:
    """Maps each asset to canned (date, ...) rows, keyed by the WHERE literal."""

    def __init__(self, fund_rows: dict[uuid.UUID, list[tuple[Any, ...]]]) -> None:
        self._fund_rows = fund_rows

    async def execute(self, stmt: Any) -> _FakeResult:
        params = stmt.compile().params
        for fund_id, rows in self._fund_rows.items():
            if fund_id in params.values():
                return _FakeResult(rows)
        return _FakeResult([])


def _nav_rows(
    n: int, start: dt.date, nav0: float = 100.0, with_return_1d: bool = True
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
        rows.append((day, nav, r if with_return_1d else None))
        day += dt.timedelta(days=1)
    return rows


def test_fund_return_series_prefers_return_1d_falls_back_to_log_nav() -> None:
    rows = [
        (dt.date(2026, 1, 5), 100.0, 0.001),
        (dt.date(2026, 1, 6), 101.0, None),  # fallback: log(101/100)
        (dt.date(2026, 1, 7), 102.0, 0.0099),
        (dt.date(2026, 1, 8), None, None),  # neither — dropped
    ]
    series = optimizer_data._fund_return_series(rows)
    assert list(series.index) == [dt.date(2026, 1, 5), dt.date(2026, 1, 6), dt.date(2026, 1, 7)]
    assert series.iloc[1] == pytest.approx(float(np.log(101.0 / 100.0)))


async def test_load_aligned_returns_intersects_dates() -> None:
    start = dt.date(2024, 7, 1)
    rows_a = _nav_rows(450, start)
    rows_b = _nav_rows(450, start, with_return_1d=False)[10:]  # shorter, shifted
    session = _FakeSession({_FUND_A: rows_a, _FUND_B: rows_b})
    frame = await optimizer_data.load_aligned_returns(
        session,  # type: ignore[arg-type]
        [optimizer_data.FundAssetRef(id=_FUND_A), optimizer_data.FundAssetRef(id=_FUND_B)],
        today=_TODAY,
    )
    assert list(frame.columns) == [f"fund:{_FUND_A}", f"fund:{_FUND_B}"]
    # B has no return_1d: first row needs a previous NAV, so one extra is lost.
    assert len(frame) >= optimizer_data.MIN_COMMON_OBS
    assert frame.notna().all().all()


async def test_load_aligned_returns_under_400_common_obs_raises() -> None:
    start = dt.date(2025, 9, 1)
    session = _FakeSession(
        {_FUND_A: _nav_rows(200, start), _FUND_B: _nav_rows(200, start)}
    )
    with pytest.raises(ValueError, match="insufficient common history"):
        await optimizer_data.load_aligned_returns(
            session,  # type: ignore[arg-type]
            [
                optimizer_data.FundAssetRef(id=_FUND_A),
                optimizer_data.FundAssetRef(id=_FUND_B),
            ],
            today=_TODAY,
        )


async def test_load_aligned_returns_unknown_asset_raises() -> None:
    session = _FakeSession({_FUND_A: _nav_rows(450, dt.date(2024, 7, 1))})
    with pytest.raises(ValueError, match="unknown asset"):
        await optimizer_data.load_aligned_returns(
            session,  # type: ignore[arg-type]
            [
                optimizer_data.FundAssetRef(id=_FUND_A),
                optimizer_data.FundAssetRef(id=_FUND_B),
            ],
            today=_TODAY,
        )


async def test_load_aligned_returns_duplicate_assets_raise() -> None:
    session = _FakeSession({})
    with pytest.raises(ValueError, match="duplicate assets"):
        await optimizer_data.load_aligned_returns(
            session,  # type: ignore[arg-type]
            [
                optimizer_data.FundAssetRef(id=_FUND_A),
                optimizer_data.FundAssetRef(id=_FUND_A),
            ],
            today=_TODAY,
        )
