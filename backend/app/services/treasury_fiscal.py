"""Treasury fiscal-data reader (Tier 1 serving layer — DB-first).

Reads the treasury_data table materialized by the treasury_ingestion worker
(repo investintell-datalake-workers, rows_from_*/upsert_treasury_data): five
Fiscal Data endpoints mapped to prefixed series ids
(RATE_/DEBT_/AUCTION_/FX_/INTEREST_). The Light only READS, filtered by
series_id prefix over a lookback window; auction metadata_json
(security_type/security_term/bid_to_cover) is passed through unchanged.
"""

import datetime as dt
from dataclasses import dataclass
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

VALID_PREFIXES = ("RATE_", "DEBT_", "AUCTION_", "FX_", "INTEREST_")


@dataclass(frozen=True)
class FiscalPoint:
    obs_date: dt.date
    value: float
    metadata: dict[str, Any] | None


@dataclass(frozen=True)
class FiscalSeries:
    series_id: str
    points: list[FiscalPoint]


@dataclass(frozen=True)
class FiscalData:
    prefix: str
    series: list[FiscalSeries]


_SERIES_SQL = text("""
    SELECT series_id, obs_date, value, metadata_json
    FROM treasury_data
    WHERE series_id LIKE :prefix
      AND obs_date >= :cutoff
      AND value IS NOT NULL
    ORDER BY series_id ASC, obs_date ASC
""")


def _today() -> dt.date:
    return dt.date.today()


async def fetch_treasury_series(
    datalake: AsyncSession, *, prefix: str, lookback_days: int
) -> FiscalData:
    """All treasury_data series for one prefix over the lookback window.

    Empty ``series`` means nothing materialized for that prefix/window — the
    route maps that to 404. Rows are grouped per series_id, ascending by date.
    """
    cutoff = _today() - dt.timedelta(days=lookback_days)
    rows = (
        await datalake.execute(
            _SERIES_SQL, {"prefix": f"{prefix}%", "cutoff": cutoff}
        )
    ).all()

    grouped: dict[str, list[FiscalPoint]] = {}
    for r in rows:
        grouped.setdefault(r.series_id, []).append(
            FiscalPoint(
                obs_date=r.obs_date,
                value=float(r.value),
                metadata=r.metadata_json,
            )
        )
    return FiscalData(
        prefix=prefix,
        series=[
            FiscalSeries(series_id=sid, points=points)
            for sid, points in grouped.items()
        ],
    )
