"""Tests for the style-box reader/orchestrator (Tier 3, T3B-1).

The cohort comes from equity_characteristics_monthly (materialized by the
datalake characteristics worker); this service only READS it via an
AsyncSession and applies the pure classifier. The DB is stubbed with a fake
async session that returns canned rows — no live cloud. The light test suite
runs under pytest asyncio_mode="auto" (pyproject.toml line 53), so the
@pytest.mark.asyncio markers below are optional but kept for clarity.
"""

import datetime as dt
import uuid

import pytest

from app.services.style_box import classify_fund_style_box, load_cohort


class _FakeResult:
    def __init__(self, rows):
        self._rows = rows

    def all(self):
        return self._rows


class _FakeSession:
    """Minimal AsyncSession stub: records the last params, returns rows.

    Mirrors how app.services.lookthrough calls the session:
    ``await datalake.execute(text_sql, {"as_of": ...})`` — params arrive as the
    second positional argument.
    """

    def __init__(self, rows):
        self._rows = rows
        self.last_params = None

    async def execute(self, _stmt, params=None):
        self.last_params = params
        return _FakeResult(self._rows)


def _row(iid, size, btm, as_of=dt.date(2026, 3, 31)):
    # Mirrors the SELECT column order in load_cohort:
    # (instrument_id, as_of, size_log_mkt_cap, book_to_market).
    return (iid, as_of, size, btm)


@pytest.mark.asyncio
async def test_load_cohort_maps_rows():
    rows = [
        _row(uuid.uuid4(), 10.0, 0.2),
        _row(uuid.uuid4(), 13.0, 0.5),
        _row(uuid.uuid4(), 16.0, 0.9),
    ]
    session = _FakeSession(rows)
    cohort = await load_cohort(session, dt.date(2026, 3, 31))
    assert len(cohort) == 3
    assert (10.0, 0.2) in cohort
    assert session.last_params["as_of"] == dt.date(2026, 3, 31)


@pytest.mark.asyncio
async def test_classify_fund_style_box_happy_path():
    target = uuid.uuid4()
    rows = [
        (target, dt.date(2026, 3, 31), 16.0, 0.9),
        (uuid.uuid4(), dt.date(2026, 3, 31), 10.0, 0.2),
        (uuid.uuid4(), dt.date(2026, 3, 31), 13.0, 0.5),
    ]
    session = _FakeSession(rows)
    box = await classify_fund_style_box(session, target, dt.date(2026, 3, 31))
    assert box.label == "large_value"


@pytest.mark.asyncio
async def test_classify_fund_style_box_missing_fund_raises():
    rows = [
        (uuid.uuid4(), dt.date(2026, 3, 31), 10.0, 0.2),
        (uuid.uuid4(), dt.date(2026, 3, 31), 13.0, 0.5),
        (uuid.uuid4(), dt.date(2026, 3, 31), 16.0, 0.9),
    ]
    session = _FakeSession(rows)
    with pytest.raises(ValueError, match="not in the style-box cohort"):
        await classify_fund_style_box(session, uuid.uuid4(), dt.date(2026, 3, 31))


@pytest.mark.asyncio
async def test_classify_fund_style_box_undersized_cohort_raises():
    target = uuid.uuid4()
    rows = [(target, dt.date(2026, 3, 31), 16.0, 0.9)]
    session = _FakeSession(rows)
    with pytest.raises(ValueError, match="at least 3 funds"):
        await classify_fund_style_box(session, target, dt.date(2026, 3, 31))
