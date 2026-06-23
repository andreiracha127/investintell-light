"""Backfill the institutional-reveal artifact cache for every catalog fund.

Computes the on-the-fly Tier C reveal per series (the compute path, NOT the
cache-first wrapper) and upserts the serialized payload into
``fund_institutional_reveal_artifacts``, then refreshes
``fund_institutional_reveal_latest_mv``. Idempotent (ON CONFLICT updates), so it
is safe to re-run after new 13F ingestion to refresh the cache.

Run from backend/ with both DSNs pointing at the data DB (same Tiger in prod):
  DATABASE_URL=<dsn> DATALAKE_DB_URL=<dsn> \
      python -m scripts.backfill_reveal_artifacts [--limit N]
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
_COMMIT_EVERY = 200


async def run(limit: int | None) -> None:
    dlmaker = _get_sessionmaker()
    written = skipped = errors = 0
    async with AsyncSessionLocal() as session, dlmaker() as datalake:
        ids = [r[0] for r in (await session.execute(text(_SELECT_FUNDS))).all()]
        if limit:
            ids = ids[:limit]
        total = len(ids)
        print(f"Backfilling reveal artifacts for {total} funds ...")
        for i, iid in enumerate(ids, 1):
            try:
                fund = await session.get(Fund, iid)
                if fund is None:
                    skipped += 1
                    continue
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
                written += 1
            except Exception as exc:  # one bad fund must not abort the sweep
                errors += 1
                print(f"  ERR {iid}: {type(exc).__name__}: {str(exc)[:140]}")
            if i % _COMMIT_EVERY == 0:
                await datalake.commit()
                await session.rollback()  # release the read snapshot
                print(f"  [{i}/{total}] written={written} skipped={skipped} errors={errors}")
        await datalake.commit()
        print(f"Done: written={written} skipped={skipped} errors={errors}")
        print("Refreshing fund_institutional_reveal_latest_mv ...")
        await datalake.execute(
            text("REFRESH MATERIALIZED VIEW fund_institutional_reveal_latest_mv")
        )
        await datalake.commit()
        print("MV refreshed.")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=None)
    args = ap.parse_args()
    asyncio.run(run(args.limit))
