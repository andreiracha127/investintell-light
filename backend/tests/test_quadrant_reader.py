from __future__ import annotations

import datetime as dt

import pytest

from app.services.quadrant_reader import (
    QuadrantSnapshotRow,
    effective_status,
    fetch_quadrant_snapshot,
)

UTC = dt.UTC


class _Result:
    def __init__(self, row):
        self._row = row

    def first(self):
        return self._row


class _Session:
    """Fake AsyncSession capturing the SQL + bound params."""

    def __init__(self, row):
        self._row = row
        self.captured = None

    async def execute(self, stmt, params=None):
        self.captured = (str(stmt), params)
        return _Result(self._row)


class _Row:
    def __init__(self, **kw):
        self.__dict__.update(kw)


def _valid_row(stale_after):
    return _Row(
        quadrant="expansion", candidate_quadrant="expansion",
        candidate_confidence=0.85, as_of=dt.date(2024, 3, 1),
        available_at=dt.datetime(2024, 3, 2, tzinfo=UTC),
        stale_after=stale_after, status_at_compute="valid",
        model_version="macro_quadrant_us_v1",
        growth_score=0.3, inflation_score=0.3, transition_pending=False,
    )


def test_effective_status_derives_stale() -> None:
    row = QuadrantSnapshotRow.from_db(_valid_row(dt.datetime(2024, 3, 3, tzinfo=UTC)))
    assert effective_status(row, dt.datetime(2024, 3, 4, tzinfo=UTC)) == "stale"
    assert effective_status(row, dt.datetime(2024, 3, 2, 12, tzinfo=UTC)) == "valid"


@pytest.mark.asyncio
async def test_fetch_returns_row_when_consumable() -> None:
    sess = _Session(_valid_row(dt.datetime(2024, 4, 1, tzinfo=UTC)))
    out = await fetch_quadrant_snapshot(
        sess, model_version="macro_quadrant_us_v1",
        decision_time=dt.datetime(2024, 3, 3, tzinfo=UTC))
    assert out is not None and out.quadrant == "expansion"


@pytest.mark.asyncio
async def test_fetch_query_filters_status_confidence_stale_and_pit() -> None:
    sess = _Session(None)
    await fetch_quadrant_snapshot(
        sess, model_version="macro_quadrant_us_v1",
        decision_time=dt.datetime(2024, 3, 3, tzinfo=UTC))
    sql, params = sess.captured
    assert "status_at_compute = 'valid'" in sql
    assert "quadrant IS NOT NULL" in sql
    assert "candidate_confidence >= 0.70" in sql
    assert "available_at <= " in sql
    assert "stale_after > " in sql
    assert "ORDER BY available_at DESC" in sql
    # forbidden: last-non-null forward-fill of any non-valid snapshot.
    assert "regime_date DESC" not in sql
    assert params["model_version"] == "macro_quadrant_us_v1"


@pytest.mark.asyncio
async def test_fetch_returns_none_when_nothing_consumable() -> None:
    sess = _Session(None)
    out = await fetch_quadrant_snapshot(
        sess, model_version="macro_quadrant_us_v1",
        decision_time=dt.datetime(2024, 3, 3, tzinfo=UTC))
    assert out is None


@pytest.mark.asyncio
async def test_fetch_returns_none_on_missing_relation() -> None:
    class _Boom:
        async def execute(self, *a, **k):
            raise RuntimeError("relation does not exist")
    out = await fetch_quadrant_snapshot(
        _Boom(), model_version="macro_quadrant_us_v1",
        decision_time=dt.datetime(2024, 3, 3, tzinfo=UTC))
    assert out is None
