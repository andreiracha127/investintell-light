"""Regional macro scorecard reader (Tier 1 serving layer — DB-first).

Reads the latest version-1 snapshot materialized by the ``macro_ingestion``
worker (repo investintell-datalake-workers, ``build_regional_snapshot``) into
``macro_regional_snapshots.data_json``, and parses it into frozen dataclasses.
No scoring here — the percentile-rank composites, staleness weights and global
indicators are all produced offline by the worker; the Light only READS.

data_json (version 1) shape, verbatim from the worker's
``build_regional_snapshot``:
  {"version": 1, "as_of_date": "YYYY-MM-DD",
   "regions": {<REGION>: {"composite_score", "coverage",
       "dimensions": {<dim>: {"score", "n_indicators", "indicators": {...}}},
       "data_freshness": {<series_id>: {"last_date", "days_stale",
                                        "weight", "status"}}}},
   "global_indicators": {"geopolitical_risk_score", "energy_stress",
                         "commodity_stress", "usd_strength"}}
"""

import datetime as dt
from dataclasses import dataclass
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


@dataclass(frozen=True)
class DimensionScore:
    score: float
    n_indicators: int
    indicators: dict[str, float]


@dataclass(frozen=True)
class DataFreshness:
    last_date: dt.date | None
    days_stale: int | None
    weight: float
    status: str


@dataclass(frozen=True)
class RegionScorecard:
    region: str
    composite_score: float
    coverage: float
    dimensions: dict[str, DimensionScore]
    data_freshness: dict[str, DataFreshness]


@dataclass(frozen=True)
class GlobalIndicators:
    geopolitical_risk_score: float
    energy_stress: float
    commodity_stress: float
    usd_strength: float


@dataclass(frozen=True)
class MacroScorecards:
    as_of_date: dt.date
    regions: dict[str, RegionScorecard]
    global_indicators: GlobalIndicators


_LATEST_SQL = text("""
    SELECT as_of_date, data_json
    FROM macro_regional_snapshots
    ORDER BY as_of_date DESC
    LIMIT 1
""")


def _parse_date(value: Any) -> dt.date | None:
    if value is None:
        return None
    if isinstance(value, dt.date):
        return value
    return dt.date.fromisoformat(str(value))


def _parse_dimension(raw: dict[str, Any]) -> DimensionScore:
    return DimensionScore(
        score=float(raw.get("score", 0.0)),
        n_indicators=int(raw.get("n_indicators", 0)),
        indicators={k: float(v) for k, v in (raw.get("indicators") or {}).items()},
    )


def _parse_freshness(raw: dict[str, Any]) -> DataFreshness:
    days = raw.get("days_stale")
    return DataFreshness(
        last_date=_parse_date(raw.get("last_date")),
        days_stale=int(days) if days is not None else None,
        weight=float(raw.get("weight", 0.0)),
        status=str(raw.get("status", "stale")),
    )


def _parse_region(name: str, raw: dict[str, Any]) -> RegionScorecard:
    return RegionScorecard(
        region=name,
        composite_score=float(raw.get("composite_score", 50.0)),
        coverage=float(raw.get("coverage", 0.0)),
        dimensions={
            dim: _parse_dimension(d) for dim, d in (raw.get("dimensions") or {}).items()
        },
        data_freshness={
            sid: _parse_freshness(f)
            for sid, f in (raw.get("data_freshness") or {}).items()
        },
    )


async def fetch_macro_scorecards(datalake: AsyncSession) -> MacroScorecards | None:
    """Latest materialized regional scorecards + global indicators, or None."""
    latest = (await datalake.execute(_LATEST_SQL)).first()
    if latest is None:
        return None
    data = latest.data_json or {}
    gi = data.get("global_indicators") or {}
    as_of_date = _parse_date(latest.as_of_date) or _parse_date(data.get("as_of_date"))
    if as_of_date is None:
        raise ValueError("macro_regional_snapshots row has no as_of_date")
    return MacroScorecards(
        as_of_date=as_of_date,
        regions={
            name: _parse_region(name, raw)
            for name, raw in (data.get("regions") or {}).items()
        },
        global_indicators=GlobalIndicators(
            geopolitical_risk_score=float(gi.get("geopolitical_risk_score", 50.0)),
            energy_stress=float(gi.get("energy_stress", 50.0)),
            commodity_stress=float(gi.get("commodity_stress", 50.0)),
            usd_strength=float(gi.get("usd_strength", 50.0)),
        ),
    )
