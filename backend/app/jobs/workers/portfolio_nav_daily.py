"""Materialize daily portfolio NAV from the real transaction ledger.

Entry point:
    python -m app.jobs.workers.portfolio_nav_daily

The job is idempotent. For each selected portfolio it rebuilds the persisted
daily NAV series from the immutable trade ledger, portfolio inception date, and
EOD/fund NAV price tables.
"""

from __future__ import annotations

import argparse
import asyncio
import datetime as dt
import json
from collections.abc import Sequence
from typing import Any

from sqlalchemy import text

from app.core.db import AsyncSessionLocal
from app.services import portfolio_ledger

ADVISORY_LOCK_ID = 900_041


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


async def run(
    *,
    portfolio_ids: Sequence[int] | None = None,
    end_date: dt.date | None = None,
) -> dict[str, Any]:
    async with AsyncSessionLocal() as session:
        if not await _acquire_lock(session):
            return {
                "status": "skipped",
                "reason": "portfolio_nav_daily worker already running",
                "lock_id": ADVISORY_LOCK_ID,
            }

        try:
            results = await portfolio_ledger.materialize_all_portfolio_nav(
                session,
                portfolio_ids=portfolio_ids,
                end_date=end_date,
            )
            await session.commit()
            return {
                "status": "ok",
                "lock_id": ADVISORY_LOCK_ID,
                "portfolios": [
                    {
                        "portfolio_id": result.portfolio_id,
                        "points": result.points,
                        "start_date": result.start_date,
                        "end_date": result.end_date,
                    }
                    for result in results
                ],
            }
        except Exception:
            await session.rollback()
            raise
        finally:
            await _release_lock(session)
            await session.commit()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Materialize daily portfolio NAV from portfolio_transactions."
    )
    parser.add_argument(
        "--portfolio-id",
        action="append",
        type=int,
        dest="portfolio_ids",
        help=(
            "Portfolio id to refresh. Repeat for multiple portfolios. "
            "Defaults to all portfolios with ledger rows."
        ),
    )
    parser.add_argument(
        "--end-date",
        type=str,
        default=None,
        help="Last NAV date to materialize (YYYY-MM-DD). Defaults to today.",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> None:
    args = build_parser().parse_args(argv)
    result = asyncio.run(
        run(
            portfolio_ids=args.portfolio_ids,
            end_date=_parse_date(args.end_date),
        )
    )
    print(json.dumps(result, default=_json_default, sort_keys=True))


if __name__ == "__main__":
    main()
