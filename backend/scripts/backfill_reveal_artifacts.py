"""Backfill the institutional-reveal artifact cache for every catalog fund.

Computes the on-the-fly Tier C reveal per series (the compute path, NOT the
cache-first wrapper) and upserts the serialized payload into
``fund_institutional_reveal_artifacts``, then refreshes
``fund_institutional_reveal_latest_mv``. Idempotent (ON CONFLICT updates), so it
is safe to re-run after new 13F ingestion to refresh the cache.

The work is latency-bound (a few small queries per fund), so funds are processed
with bounded ``asyncio`` concurrency — each task owns its own session pair, which
hides cross-region round-trip latency. Concurrency stays within the engine pool
ceilings (main 20, datalake 15).

Run from backend/ with both DSNs pointing at the data DB (same Tiger in prod):
  DATABASE_URL=<dsn> DATALAKE_DB_URL=<dsn> \
      python -u -m scripts.backfill_reveal_artifacts [--limit N] [--concurrency N]
"""

from __future__ import annotations

import argparse
import asyncio
import datetime as dt
import json

from sqlalchemy import text

from app.core.datalake import _get_sessionmaker
from app.core.db import AsyncSessionLocal
from app.models.fund import Fund
from app.services.fund_dossier_tier_b import (
    _REVEAL_SCHEMA_VERSION,
    _compute_fund_institutional_reveal,
)

_SELECT_FUNDS = (
    "SELECT instrument_id FROM funds_list_mv ORDER BY aum_usd DESC NULLS LAST"
)
_UPSERT = """
INSERT INTO fund_institutional_reveal_artifacts
    (series_id, as_of, schema_version, payload, organization_id, computed_at)
VALUES (:series_id, :as_of, :ver, CAST(:payload AS jsonb), NULL, now())
ON CONFLICT (series_id, as_of, organization_id)
DO UPDATE SET payload = EXCLUDED.payload,
              schema_version = EXCLUDED.schema_version,
              computed_at = now()
"""
_DEFAULT_CONCURRENCY = 10


async def _process_one(iid, sem: asyncio.Semaphore, dlmaker, counters: dict) -> None:
    async with sem:
        try:
            async with AsyncSessionLocal() as session, dlmaker() as datalake:
                fund = await session.get(Fund, iid)
                if fund is None:
                    counters["skipped"] += 1
                    return
                resp = await _compute_fund_institutional_reveal(session, datalake, fund)
                as_of = resp.period or resp.holdings_report_date or dt.date.today()
                await datalake.execute(
                    text(_UPSERT),
                    {
                        "series_id": fund.series_id,
                        "as_of": as_of,
                        "ver": _REVEAL_SCHEMA_VERSION,
                        "payload": json.dumps(resp.model_dump(mode="json")),
                    },
                )
                await datalake.commit()
                counters["written"] += 1
        except Exception as exc:  # one bad fund must not abort the sweep
            counters["errors"] += 1
            if counters["errors"] <= 20:
                print(f"  ERR {iid}: {type(exc).__name__}: {str(exc)[:140]}")


async def run(limit: int | None, concurrency: int) -> None:
    dlmaker = _get_sessionmaker()
    counters = {"written": 0, "skipped": 0, "errors": 0}
    async with AsyncSessionLocal() as s0:
        ids = [r[0] for r in (await s0.execute(text(_SELECT_FUNDS))).all()]
    if limit:
        ids = ids[:limit]
    total = len(ids)
    print(f"Backfilling {total} funds (concurrency={concurrency}) ...")
    sem = asyncio.Semaphore(concurrency)
    tasks = [asyncio.create_task(_process_one(iid, sem, dlmaker, counters)) for iid in ids]
    done = 0
    for fut in asyncio.as_completed(tasks):
        await fut
        done += 1
        if done % 500 == 0:
            print(
                f"  [{done}/{total}] written={counters['written']} "
                f"skipped={counters['skipped']} errors={counters['errors']}"
            )
    print(f"Done: {counters}")
    async with dlmaker() as datalake:
        print("Refreshing fund_institutional_reveal_latest_mv ...")
        await datalake.execute(
            text("REFRESH MATERIALIZED VIEW fund_institutional_reveal_latest_mv")
        )
        await datalake.commit()
        print("MV refreshed.")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--concurrency", type=int, default=_DEFAULT_CONCURRENCY)
    args = ap.parse_args()
    asyncio.run(run(args.limit, args.concurrency))
