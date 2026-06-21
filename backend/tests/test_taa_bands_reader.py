"""Unit tests for the ``regime_gate_daily`` reader (``fetch_gate_regime``).

Uses a fake async session so no real data-lake / ``regime_gate_daily`` table is
required. Mirrors the row-mapping idiom of ``macro_regime.fetch_composite_regime``.
"""

import datetime as dt

import pytest

from app.services import taa_bands as tb


class _Result:
    def __init__(self, row):
        self._row = row

    def first(self):
        return self._row


class _FakeSession:
    def __init__(self, row):
        self._row = row

    async def execute(self, *a, **k):
        return _Result(self._row)


class _Row:
    """A lightweight attribute-access row matching SQLAlchemy ``.first()`` output."""

    def __init__(self, **kw):
        self.__dict__.update(kw)


@pytest.mark.asyncio
async def test_fetch_gate_regime_maps_row():
    row = _Row(regime_date=dt.date(2026, 6, 18), state="risk_off",
               vote_count=2, trend_vote=True, credit_vote=True,
               drawdown_vote=False, dwell_days=35,
               growth_score=-0.04, inflation_score=0.02, quadrant="slowdown")
    snap = await tb.fetch_gate_regime(_FakeSession(row))
    assert snap.state == "risk_off"
    assert snap.as_of == dt.date(2026, 6, 18)
    assert snap.dwell_days == 35
    assert snap.quadrant == "slowdown"
    assert snap.growth_score == -0.04


@pytest.mark.asyncio
async def test_fetch_gate_regime_empty_is_none():
    assert await tb.fetch_gate_regime(_FakeSession(None)) is None


@pytest.mark.asyncio
async def test_fetch_gate_regime_defaults_missing_quadrant_columns():
    # An older Sprint-1 table without the decision-A columns: reader must not crash.
    row = _Row(regime_date=dt.date(2026, 6, 10), state="risk_on",
               vote_count=0, trend_vote=False, credit_vote=False,
               drawdown_vote=False, dwell_days=10)
    snap = await tb.fetch_gate_regime(_FakeSession(row))
    assert snap.state == "risk_on"
    assert snap.quadrant is None
    assert snap.growth_score is None
    assert snap.inflation_score is None
