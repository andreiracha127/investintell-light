"""Persistence service for ``portfolio_drift_status`` (Sprint C, Task 1).

Async CRUD helpers over the one-row-per-portfolio drift status. Routes / the
worker own HTTP mapping and the transaction boundary; this module owns the
SQL/ORM and ``flush``es (so changes are visible within the session) but does
not ``commit``. Later Sprint C tasks add the evaluation logic, worker and
endpoint; this task is the persistence layer only.

Contract:

- ``upsert_drift_status`` writes the portfolio's drift row (insert if absent,
  update in place if present), so a re-evaluation never leaves a duplicate.
- ``get_drift_status`` returns a small typed ``DriftStatus`` (the four logical
  fields), or ``None`` if the portfolio has never been evaluated.

Every update stamps ``updated_at`` explicitly (the ORM ``onupdate`` hook only
fires on ORM updates; setting it here keeps the timestamp correct regardless of
how the update is emitted — same caveat as the portfolio / optimize_jobs /
constraint tables).
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.portfolio_drift_status import PortfolioDriftStatus


@dataclass(frozen=True)
class DriftStatus:
    """The latest drift evaluation for a portfolio."""

    portfolio_id: int
    evaluated_at: dt.datetime
    worst_status: str
    breaches: dict


async def upsert_drift_status(
    session: AsyncSession,
    portfolio_id: int,
    *,
    evaluated_at: dt.datetime,
    worst_status: str,
    breaches: dict,
) -> None:
    """Upsert the drift status for ``portfolio_id``.

    Inserts a new row if the portfolio has no drift status yet, otherwise
    updates the existing row in place (one row per portfolio, no duplicates).
    """
    row = await session.get(PortfolioDriftStatus, portfolio_id)
    if row is None:
        row = PortfolioDriftStatus(
            portfolio_id=portfolio_id,
            evaluated_at=evaluated_at,
            worst_status=worst_status,
            breaches=breaches,
        )
        session.add(row)
    else:
        row.evaluated_at = evaluated_at
        row.worst_status = worst_status
        row.breaches = breaches
        row.updated_at = dt.datetime.now(dt.UTC)

    await session.flush()


async def get_drift_status(
    session: AsyncSession, portfolio_id: int
) -> DriftStatus | None:
    """Return the typed drift status for ``portfolio_id``, or ``None``.

    ``None`` means the portfolio has never been evaluated.
    """
    row = await session.get(PortfolioDriftStatus, portfolio_id)
    if row is None:
        return None
    return DriftStatus(
        portfolio_id=row.portfolio_id,
        evaluated_at=row.evaluated_at,
        worst_status=row.worst_status,
        breaches=row.breaches,
    )
