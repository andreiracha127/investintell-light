"""Consumable QuadrantSnapshot reader (freeze v1 §6/§8).

Reads ONLY snapshots that are valid, fresh, confident, and available at the
decision time — NEVER the 'last non-null quadrant'. A missing/ambiguous/stale/
invalid snapshot yields None; the caller (portfolio builder / Policy Core) turns
that into QUADRANT_UNAVAILABLE + no-trade. The gate reader (fetch_gate_regime over
regime_gate_daily) is a SEPARATE dimension and is unchanged by this module.

This queries the BASE TABLE (not the regime_quadrant_current_v view), binding
``decision_time`` for both the point-in-time and staleness filters so a backtest
never sees the future; the view (which cuts with now()) is the ops/dashboard
accessor where now() is the only relevant decision time.
"""
from __future__ import annotations

import datetime as _dt
from dataclasses import dataclass
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


@dataclass(frozen=True)
class QuadrantSnapshotRow:
    quadrant: str
    candidate_quadrant: str | None
    candidate_confidence: float | None
    as_of: _dt.date
    available_at: _dt.datetime
    stale_after: _dt.datetime
    status_at_compute: str
    model_version: str
    growth_score: float | None
    inflation_score: float | None
    transition_pending: bool

    @classmethod
    def from_db(cls, row: Any) -> QuadrantSnapshotRow:
        def f(v: Any) -> float | None:
            return float(v) if v is not None else None
        return cls(
            quadrant=row.quadrant,
            candidate_quadrant=getattr(row, "candidate_quadrant", None),
            candidate_confidence=f(getattr(row, "candidate_confidence", None)),
            as_of=row.as_of,
            available_at=row.available_at,
            stale_after=row.stale_after,
            status_at_compute=row.status_at_compute,
            model_version=row.model_version,
            growth_score=f(getattr(row, "growth_score", None)),
            inflation_score=f(getattr(row, "inflation_score", None)),
            transition_pending=bool(getattr(row, "transition_pending", False)),
        )


def effective_status(row: QuadrantSnapshotRow, now: _dt.datetime) -> str:
    """Freeze §3: valid -> 'stale' once now >= stale_after; else pass through."""
    if row.status_at_compute == "valid" and now >= row.stale_after:
        return "stale"
    return row.status_at_compute


_CONSUMABLE_SQL = text("""
    SELECT quadrant, candidate_quadrant, candidate_confidence, as_of,
           available_at, stale_after, status_at_compute, model_version,
           growth_score, inflation_score, transition_pending
    FROM regime_quadrant_snapshot
    WHERE status_at_compute = 'valid'
      AND quadrant IS NOT NULL
      AND candidate_confidence >= 0.70
      AND model_version = :model_version
      AND available_at <= :decision_time
      AND stale_after > :decision_time
    ORDER BY available_at DESC
    LIMIT 1
""")


async def fetch_quadrant_snapshot(
    datalake: AsyncSession,
    *,
    model_version: str,
    decision_time: _dt.datetime,
) -> QuadrantSnapshotRow | None:
    """Latest consumable quadrant snapshot, or None (caller -> QUADRANT_UNAVAILABLE).

    ``decision_time`` is now() in production and the bar's decision time in
    backtest; it is used for BOTH the point-in-time filter (available_at <=) and
    the staleness filter (stale_after >), so a backtest never sees the future.
    """
    try:
        result = await datalake.execute(
            _CONSUMABLE_SQL,
            {"model_version": model_version, "decision_time": decision_time},
        )
        row = result.first()
    except Exception:
        return None
    if row is None:
        return None
    return QuadrantSnapshotRow.from_db(row)
