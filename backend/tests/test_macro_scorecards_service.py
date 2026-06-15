"""Unit tests for app/services/macro_scorecards.py (DB-first snapshot reader).

The regional scorecard + global indicators are COMPUTED by the macro_ingestion
worker (repo investintell-datalake-workers, build_regional_snapshot) and
materialized into macro_regional_snapshots.data_json (version 1). The Light only
READS the latest row and parses it — no scoring here. A fake async session feeds
canned rows; no live cloud, no live DB.
"""

import datetime as dt
from typing import Any

from app.services import macro_scorecards as ms

_DATA_JSON: dict[str, Any] = {
    "version": 1,
    "as_of_date": "2026-06-14",
    "regions": {
        "US": {
            "composite_score": 47.72,
            "coverage": 0.85,
            "dimensions": {
                "growth": {
                    "score": 57.93,
                    "n_indicators": 4,
                    "indicators": {"CFNAI": 68.07, "PAYEMS": 100.0},
                },
            },
            "data_freshness": {
                "CPIAUCSL": {
                    "last_date": "2026-05-31",
                    "days_stale": 14,
                    "weight": 1.0,
                    "status": "fresh",
                },
                "JTSJOL": {
                    "last_date": None,
                    "days_stale": None,
                    "weight": 0.0,
                    "status": "stale",
                },
            },
        },
        "EUROPE": {
            "composite_score": 52.10,
            "coverage": 0.60,
            "dimensions": {},
            "data_freshness": {},
        },
    },
    "global_indicators": {
        "geopolitical_risk_score": 81.51,
        "energy_stress": 55.59,
        "commodity_stress": 100.0,
        "usd_strength": 54.36,
    },
}


class _FakeResult:
    def __init__(self, row: Any) -> None:
        self._row = row

    def first(self) -> Any:
        return self._row


class _FakeRow:
    def __init__(self, as_of_date: dt.date, data_json: dict[str, Any]) -> None:
        self.as_of_date = as_of_date
        self.data_json = data_json


class _FakeSession:
    def __init__(self, row: Any) -> None:
        self._row = row
        self.executed = 0

    async def execute(self, stmt: Any, params: Any = None) -> _FakeResult:
        self.executed += 1
        return _FakeResult(self._row)


async def test_fetch_macro_scorecards_parses_latest_snapshot() -> None:
    session = _FakeSession(_FakeRow(dt.date(2026, 6, 14), _DATA_JSON))
    result = await ms.fetch_macro_scorecards(session)  # type: ignore[arg-type]
    assert result is not None
    assert result.as_of_date == dt.date(2026, 6, 14)
    assert set(result.regions) == {"US", "EUROPE"}
    us = result.regions["US"]
    assert us.region == "US"
    assert us.composite_score == 47.72
    assert us.coverage == 0.85
    growth = us.dimensions["growth"]
    assert growth.score == 57.93
    assert growth.n_indicators == 4
    assert growth.indicators["PAYEMS"] == 100.0
    fresh = us.data_freshness["CPIAUCSL"]
    assert fresh.last_date == dt.date(2026, 5, 31)
    assert fresh.days_stale == 14
    assert fresh.weight == 1.0
    assert fresh.status == "fresh"
    stale = us.data_freshness["JTSJOL"]
    assert stale.last_date is None
    assert stale.days_stale is None
    assert stale.status == "stale"
    g = result.global_indicators
    assert g.geopolitical_risk_score == 81.51
    assert g.energy_stress == 55.59
    assert g.commodity_stress == 100.0
    assert g.usd_strength == 54.36


async def test_fetch_macro_scorecards_none_when_not_materialized() -> None:
    session = _FakeSession(None)
    assert await ms.fetch_macro_scorecards(session) is None  # type: ignore[arg-type]


async def test_fetch_macro_scorecards_tolerates_missing_freshness_keys() -> None:
    minimal = {
        "version": 1,
        "as_of_date": "2026-06-14",
        "regions": {
            "ASIA": {
                "composite_score": 50.0,
                "coverage": 0.0,
                "dimensions": {},
                "data_freshness": {
                    "X": {"weight": 0.5, "status": "decaying"},
                },
            },
        },
        "global_indicators": {
            "geopolitical_risk_score": 50.0,
            "energy_stress": 50.0,
            "commodity_stress": 50.0,
            "usd_strength": 50.0,
        },
    }
    session = _FakeSession(_FakeRow(dt.date(2026, 6, 14), minimal))
    result = await ms.fetch_macro_scorecards(session)  # type: ignore[arg-type]
    assert result is not None
    fr = result.regions["ASIA"].data_freshness["X"]
    assert fr.last_date is None
    assert fr.days_stale is None
    assert fr.weight == 0.5
    assert fr.status == "decaying"
