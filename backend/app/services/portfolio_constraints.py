"""Persistence service for per-portfolio construction limits (Sprint B, Task 2).

Async CRUD helpers over ``portfolio_constraint_set`` (1:1 header) and
``portfolio_class_limits`` (per-asset-class rows). Routes / the save flow own
HTTP mapping and the transaction boundary; this module owns the SQL/ORM and
flushes (so changes are visible within the session) but does not commit.

Contract:

- ``upsert_constraints`` writes the header (insert or update in place) and
  *replaces* the portfolio's class-limit rows wholesale (delete-then-insert),
  so a second call with a different set never leaves duplicates or stale rows.
- ``get_constraints`` returns a small typed ``ConstraintSet`` (header fields +
  list of class limits), or ``None`` if no header exists for the portfolio.

Every mutation stamps ``updated_at`` explicitly on an existing header (the ORM
``onupdate`` hook only fires on ORM updates; setting it here keeps the
timestamp correct regardless of how the update is emitted — same caveat as the
portfolio / optimize_jobs tables).
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.portfolio_constraint import (
    PortfolioClassLimit,
    PortfolioConstraintSet,
)


@dataclass(frozen=True)
class ClassLimit:
    """One per-asset-class min/max weight bound."""

    asset_class: str
    min_weight: float | None
    max_weight: float | None


@dataclass(frozen=True)
class ConstraintSet:
    """The header limits for a portfolio plus its per-class limits."""

    portfolio_id: int
    cap: float | None
    min_weight: float | None
    overlap_cap: float | None
    class_limits: list[ClassLimit]


async def upsert_constraints(
    session: AsyncSession,
    portfolio_id: int,
    *,
    cap: float | None,
    min_weight: float | None,
    overlap_cap: float | None,
    class_limits: list[tuple[str, float | None, float | None]],
) -> None:
    """Upsert the header and replace the class-limit rows for ``portfolio_id``.

    The header is inserted if absent or updated in place if present. The
    portfolio's existing class-limit rows are deleted and re-inserted from
    ``class_limits`` (a list of ``(asset_class, min_weight, max_weight)``
    tuples), so the persisted set always exactly matches the argument.
    """
    header = await session.get(PortfolioConstraintSet, portfolio_id)
    if header is None:
        header = PortfolioConstraintSet(
            portfolio_id=portfolio_id,
            cap=cap,
            min_weight=min_weight,
            overlap_cap=overlap_cap,
        )
        session.add(header)
    else:
        header.cap = cap
        header.min_weight = min_weight
        header.overlap_cap = overlap_cap
        header.updated_at = dt.datetime.now(dt.UTC)

    # Replace class-limit rows wholesale: delete then re-insert.
    await session.execute(
        delete(PortfolioClassLimit).where(
            PortfolioClassLimit.portfolio_id == portfolio_id
        )
    )
    for asset_class, lo, hi in class_limits:
        session.add(
            PortfolioClassLimit(
                portfolio_id=portfolio_id,
                asset_class=asset_class,
                min_weight=lo,
                max_weight=hi,
            )
        )

    await session.flush()


async def get_constraints(
    session: AsyncSession, portfolio_id: int
) -> ConstraintSet | None:
    """Return the typed constraint set for ``portfolio_id``, or ``None``.

    ``None`` means no header row exists (the portfolio was never saved with
    constraints).
    """
    header = await session.get(PortfolioConstraintSet, portfolio_id)
    if header is None:
        return None

    rows = (
        await session.execute(
            select(PortfolioClassLimit)
            .where(PortfolioClassLimit.portfolio_id == portfolio_id)
            .order_by(PortfolioClassLimit.asset_class)
        )
    ).scalars().all()

    return ConstraintSet(
        portfolio_id=portfolio_id,
        cap=header.cap,
        min_weight=header.min_weight,
        overlap_cap=header.overlap_cap,
        class_limits=[
            ClassLimit(
                asset_class=row.asset_class,
                min_weight=row.min_weight,
                max_weight=row.max_weight,
            )
            for row in rows
        ],
    )
