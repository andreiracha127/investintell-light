"""Unit tests for app/services/treasury_fiscal.py (DB-first treasury reader).

treasury_data is materialized by the treasury_ingestion worker (repo
investintell-datalake-workers, rows_from_*/upsert_treasury_data). The Light only
READS, filtered by series_id prefix over a lookback window. A fake async session
feeds canned rows; no live DB.
"""

import datetime as dt
from typing import Any

from app.services import treasury_fiscal as tf


class _FakeResult:
    def __init__(self, rows: list[Any]) -> None:
        self._rows = rows

    def all(self) -> list[Any]:
        return self._rows


class _FakeRow:
    def __init__(self, series_id: str, obs_date: dt.date, value: float,
                 metadata_json: dict[str, Any] | None = None) -> None:
        self.series_id = series_id
        self.obs_date = obs_date
        self.value = value
        self.metadata_json = metadata_json


class _FakeSession:
    def __init__(self, rows: list[Any]) -> None:
        self._rows = rows
        self.params: dict[str, Any] | None = None

    async def execute(self, stmt: Any, params: Any = None) -> _FakeResult:
        self.params = params
        return _FakeResult(self._rows)


async def test_fetch_treasury_series_groups_by_series_id() -> None:
    rows = [
        _FakeRow("RATE_TREASURY_BILLS", dt.date(2026, 5, 1), 5.05),
        _FakeRow("RATE_TREASURY_BILLS", dt.date(2026, 6, 1), 5.10),
        _FakeRow("RATE_TREASURY_NOTES", dt.date(2026, 6, 1), 4.20),
    ]
    session = _FakeSession(rows)
    result = await tf.fetch_treasury_series(
        session, prefix="RATE_", lookback_days=365,  # type: ignore[arg-type]
    )
    assert result.prefix == "RATE_"
    assert {s.series_id for s in result.series} == {
        "RATE_TREASURY_BILLS", "RATE_TREASURY_NOTES"
    }
    bills = next(s for s in result.series if s.series_id == "RATE_TREASURY_BILLS")
    # The SQL orders ascending by date within a series; the service preserves order.
    assert [p.obs_date for p in bills.points] == [
        dt.date(2026, 5, 1), dt.date(2026, 6, 1)
    ]
    assert [p.value for p in bills.points] == [5.05, 5.10]
    assert bills.points[0].metadata is None


async def test_fetch_treasury_series_passes_metadata_through() -> None:
    meta = {"security_type": "Bond", "security_term": "30-Year", "bid_to_cover": 2.4}
    rows = [_FakeRow("AUCTION_BOND_30_YEAR", dt.date(2026, 6, 11), 5.02, meta)]
    session = _FakeSession(rows)
    result = await tf.fetch_treasury_series(
        session, prefix="AUCTION_", lookback_days=365,  # type: ignore[arg-type]
    )
    pt = result.series[0].points[0]
    assert pt.metadata == meta
    assert pt.value == 5.02


async def test_fetch_treasury_series_cutoff_uses_lookback(monkeypatch) -> None:
    monkeypatch.setattr(tf, "_today", lambda: dt.date(2026, 6, 14))
    session = _FakeSession([])
    result = await tf.fetch_treasury_series(
        session, prefix="DEBT_", lookback_days=30,  # type: ignore[arg-type]
    )
    assert result.series == []
    assert session.params["prefix"] == "DEBT_%"
    assert session.params["cutoff"] == dt.date(2026, 5, 15)
