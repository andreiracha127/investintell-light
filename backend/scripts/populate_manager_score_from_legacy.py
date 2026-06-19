"""Backfill manager_score + elite_flag into the cloud fund_risk_metrics from the
legacy (mother) DB, where the allocation scoring model already populated them.

Temporary bridge until the scoring model is ported to the datalake worker: it
copies the LATEST score per instrument from local -> cloud (latest calc_date),
matched on instrument_id (the cloud is a mirror of the mother DB, same UUIDs).

Usage:
    LOCAL_DSN=postgresql://investintell:investintell@localhost:5434/investintell_alloc \
    CLOUD_DSN=postgresql://tsdbadmin:...@...tsdb.cloud.timescale.com:33132/tsdb \
    python -m scripts.populate_manager_score_from_legacy --dry-run
"""
from __future__ import annotations

import argparse
import asyncio
import os

_LOCAL_DEFAULT = "postgresql://investintell:investintell@localhost:5434/investintell_alloc"

_READ_LOCAL = """
SELECT DISTINCT ON (instrument_id) instrument_id, manager_score, elite_flag
FROM fund_risk_metrics
WHERE organization_id IS NULL AND manager_score IS NOT NULL
ORDER BY instrument_id, calc_date DESC
"""


async def main(dry_run: bool) -> None:
    import asyncpg

    local_dsn = os.environ.get("LOCAL_DSN", _LOCAL_DEFAULT)
    cloud_dsn = os.environ["CLOUD_DSN"]

    local = await asyncpg.connect(local_dsn)
    rows = await local.fetch(_READ_LOCAL)
    await local.close()
    print(f"local: {len(rows)} instruments with a manager_score")

    cloud = await asyncpg.connect(cloud_dsn, ssl="require")
    try:
        max_date = await cloud.fetchval(
            "SELECT max(calc_date) FROM fund_risk_metrics WHERE organization_id IS NULL"
        )
        await cloud.execute(
            "CREATE TEMP TABLE _ms (instrument_id uuid, manager_score numeric, elite_flag boolean)"
        )
        await cloud.copy_records_to_table(
            "_ms",
            records=[(r["instrument_id"], r["manager_score"], r["elite_flag"]) for r in rows],
        )
        target = await cloud.fetchval(
            "SELECT count(*) FROM fund_risk_metrics WHERE calc_date=$1 AND organization_id IS NULL",
            max_date,
        )
        matched = await cloud.fetchval(
            """
            SELECT count(*) FROM fund_risk_metrics f
            JOIN _ms t ON t.instrument_id = f.instrument_id
            WHERE f.calc_date = $1 AND f.organization_id IS NULL
            """,
            max_date,
        )
        print(f"cloud latest calc_date={max_date}: {target} instruments, "
              f"{matched} match a legacy score ({100*matched/target:.1f}%)")

        if dry_run:
            print("[dry-run] no writes")
            return

        await cloud.execute(
            """
            UPDATE fund_risk_metrics f
            SET manager_score = t.manager_score, elite_flag = t.elite_flag
            FROM _ms t
            WHERE t.instrument_id = f.instrument_id
              AND f.calc_date = $1 AND f.organization_id IS NULL
            """,
            max_date,
        )
        populated = await cloud.fetchval(
            "SELECT count(manager_score) FROM fund_risk_metrics "
            "WHERE calc_date=$1 AND organization_id IS NULL",
            max_date,
        )
        print(f"updated; cloud now has {populated} manager_score at {max_date}")
    finally:
        await cloud.close()


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    asyncio.run(main(args.dry_run))
