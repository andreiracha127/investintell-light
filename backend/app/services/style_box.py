"""Style-box reader/orchestrator (Tier 3, T3B-1) — DB-first, read-only.

The size/value characteristics are materialized by the datalake
``characteristics`` worker in ``equity_characteristics_monthly`` (TimescaleDB
Cloud). This service only READS that table via an AsyncSession and applies the
pure classifier in ``app.analytics.style_box`` — no characteristic math here.

Pattern mirrors ``app.services.lookthrough``: ``text()`` SQL against the
materialized data-lake table + a thin pure-fn call. Fail-loud: ValueError
(mapped to 422 by the route) when the cohort is too small or the target fund is
absent.
"""

from __future__ import annotations

import datetime as dt
import uuid

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.analytics.style_box import (
    StyleBox,
    classify_style_box,
    compute_breakpoints,
)

# Latest as_of for each instrument on/before the requested date, then the
# size/value chars for that snapshot. equity_characteristics_monthly is keyed
# (instrument_id, as_of); we take the most recent row per fund <= as_of.
_COHORT_SQL = text("""
    SELECT DISTINCT ON (instrument_id)
           instrument_id, as_of, size_log_mkt_cap, book_to_market
    FROM equity_characteristics_monthly
    WHERE as_of <= :as_of
      AND size_log_mkt_cap IS NOT NULL
      AND book_to_market IS NOT NULL
    ORDER BY instrument_id, as_of DESC
""")


async def load_cohort(
    datalake: AsyncSession, as_of: dt.date
) -> list[tuple[float, float]]:
    """Cross-sectional (size_log_mkt_cap, book_to_market) cohort as-of a date."""
    result = await datalake.execute(_COHORT_SQL, {"as_of": as_of})
    return [(float(size), float(btm)) for _iid, _as_of, size, btm in result.all()]


async def _load_cohort_with_ids(
    datalake: AsyncSession, as_of: dt.date
) -> list[tuple[uuid.UUID, float, float]]:
    result = await datalake.execute(_COHORT_SQL, {"as_of": as_of})
    return [
        (iid, float(size), float(btm))
        for iid, _as_of, size, btm in result.all()
    ]


async def classify_fund_style_box(
    datalake: AsyncSession, instrument_id: uuid.UUID, as_of: dt.date
) -> StyleBox:
    """Classify one fund against the as-of cross-sectional cohort.

    Raises ValueError when the cohort has < 3 funds or the target fund has no
    materialized characteristics on/before ``as_of``.
    """
    cohort = await _load_cohort_with_ids(datalake, as_of)
    breakpoints = compute_breakpoints([(s, b) for _iid, s, b in cohort])
    for iid, size, btm in cohort:
        if iid == instrument_id:
            return classify_style_box(size, btm, breakpoints)
    raise ValueError(
        f"fund {instrument_id} not in the style-box cohort as-of {as_of}"
    )
