"""Materialize the daily portfolio drift status for every portfolio.

Entry point:
    python -m app.jobs.workers.portfolio_drift_daily [--portfolio-id N ...] [--as-of YYYY-MM-DD]

The job is idempotent. For each selected portfolio it re-evaluates drift vs the
inception target, asset-class limit breaches and equity-overlap breaches, then
upserts the single ``portfolio_drift_status`` row (never a duplicate). Mirrors
``portfolio_nav_daily``: one advisory lock so concurrent runs don't pile up, an
optional read-only data-lake session for the N-PORT look-through (graceful
``None`` when ``DATALAKE_DB_URL`` is unset), commit on success, lock released in
``finally``.
"""

from __future__ import annotations

import argparse
import asyncio
import datetime as dt
import json
from collections.abc import AsyncIterator, Sequence
from contextlib import asynccontextmanager
from typing import Any

from sqlalchemy import text
from sqlalchemy.exc import DatabaseError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import datalake as datalake_module
from app.core.config import get_settings
from app.core.db import AsyncSessionLocal
from app.services import portfolio_drift

ADVISORY_LOCK_ID = 900_042


def _parse_date(value: str | None) -> dt.date | None:
    return dt.date.fromisoformat(value) if value else None


def _json_default(value: Any) -> str:
    if isinstance(value, dt.date):
        return value.isoformat()
    raise TypeError(f"Object of type {type(value).__name__} is not JSON serializable")


async def _acquire_lock(session: Any) -> bool:
    acquired = await session.scalar(
        text("select pg_try_advisory_lock(:lock_id)"),
        {"lock_id": ADVISORY_LOCK_ID},
    )
    return bool(acquired)


async def _release_lock(session: Any) -> None:
    await session.execute(
        text("select pg_advisory_unlock(:lock_id)"),
        {"lock_id": ADVISORY_LOCK_ID},
    )


async def _read_gate_flip(
    datalake: AsyncSession | None,
) -> tuple[bool, str | None, dt.date | None]:
    """Read the latest ``regime_gate_daily`` row from the data-lake (COMBO).

    Returns ``(flipped, state, regime_date)`` where ``flipped`` is the latest
    row's per-day ``flip`` flag (a confirmed, 21d-debounced regime change). This
    is OBSERVATIONAL in v1 (decision C): the value is surfaced on the run/alert
    so a rebalance is explained as regime-driven, but the materialize stays
    daily/unconditional.

    Degrades gracefully to ``(False, None, None)`` when the data-lake is not
    configured (``datalake is None``) or the ``regime_gate_daily`` table is absent
    (the ``regime_gate`` worker has not run yet) — mirrors how the overlap
    evaluator degrades when the data-lake is unavailable.
    """
    if datalake is None:
        return (False, None, None)
    try:
        result = await datalake.execute(
            text(
                "SELECT regime_date, state, flip FROM regime_gate_daily "
                "ORDER BY regime_date DESC LIMIT 1"
            )
        )
    except DatabaseError:
        # Table missing / not yet materialized — observational read is best-effort.
        return (False, None, None)
    row = result.first()
    if row is None:
        return (False, None, None)
    regime_date, state, flip = row[0], row[1], row[2]
    return (bool(flip), state, regime_date)


@asynccontextmanager
async def _open_datalake() -> AsyncIterator[AsyncSession | None]:
    """Yield a read-only data-lake session, or None when no DSN is configured.

    Mirrors ``get_optional_datalake_session`` / the optimize job: the data-lake
    backs the look-through overlap evaluation, but a missing DSN degrades
    gracefully (the drift evaluator records an empty overlap set).
    """
    if not get_settings().datalake_db_url:
        yield None
        return
    async with datalake_module._get_sessionmaker()() as datalake_session:
        yield datalake_session


async def run(
    *,
    portfolio_ids: Sequence[int] | None = None,
    as_of: dt.date | None = None,
) -> dict[str, Any]:
    async with AsyncSessionLocal() as session:
        if not await _acquire_lock(session):
            return {
                "status": "skipped",
                "reason": "portfolio_drift_daily worker already running",
                "lock_id": ADVISORY_LOCK_ID,
            }

        try:
            async with _open_datalake() as datalake:
                # COMBO (observational v1): read the latest confirmed gate flip
                # from the same read-only data-lake session BEFORE materializing,
                # so a regime-driven rebalance is auditable. The materialize stays
                # daily/unconditional (decision C) — the flip is surfaced, not gated.
                gate_flip, gate_state, _gate_date = await _read_gate_flip(datalake)
                result = await portfolio_drift.materialize_all_portfolio_drifts(
                    session,
                    datalake,
                    portfolio_ids=list(portfolio_ids) if portfolio_ids else None,
                    as_of=as_of,
                )
            await session.commit()
            return {
                "status": "ok",
                "lock_id": ADVISORY_LOCK_ID,
                "portfolios": result["portfolios"],
                "gate_flip": gate_flip,
                "gate_state": gate_state,
            }
        except Exception:
            await session.rollback()
            raise
        finally:
            await _release_lock(session)
            await session.commit()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Materialize daily portfolio drift status for every portfolio."
    )
    parser.add_argument(
        "--portfolio-id",
        action="append",
        type=int,
        dest="portfolio_ids",
        help=(
            "Portfolio id to re-evaluate. Repeat for multiple portfolios. "
            "Defaults to all portfolios."
        ),
    )
    parser.add_argument(
        "--as-of",
        type=str,
        default=None,
        help="Evaluation date (YYYY-MM-DD). Defaults to today.",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> None:
    args = build_parser().parse_args(argv)
    result = asyncio.run(
        run(
            portfolio_ids=args.portfolio_ids,
            as_of=_parse_date(args.as_of),
        )
    )
    print(json.dumps(result, default=_json_default, sort_keys=True))


if __name__ == "__main__":
    main()
