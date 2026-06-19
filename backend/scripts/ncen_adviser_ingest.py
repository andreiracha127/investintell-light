"""Ingest the N-CEN primary investment adviser per fund series into the
``sec_fund_adviser`` crosswalk (TimescaleDB Cloud).

Source of truth: SEC Form N-CEN ``ADVISER.tsv`` (one row per fund/adviser).
We keep the PRIMARY adviser (ADVISER_TYPE == 'Advisor', not Subadvisor /
Terminated), newest quarter wins. The CRD links to ``sec_managers`` (Form ADV)
for the canonical firm name; ADVISER_NAME is the N-CEN fallback.

Idempotent upsert keyed on series_id.

Usage:
    NCEN_DSN=postgresql://... \
    python -m scripts.ncen_adviser_ingest --ncen-root "F:/EDGAR FILES/ncen"
"""
from __future__ import annotations

import argparse
import asyncio
import os
from pathlib import Path

from scripts.ncen_adviser_analyze import resolve_primary_advisers

_DDL = """
CREATE TABLE IF NOT EXISTS sec_fund_adviser (
    series_id    text PRIMARY KEY,
    cik          text,
    adviser_name text,
    adviser_crd  text,
    file_num     text,
    source       text NOT NULL DEFAULT 'ncen',
    updated_at   timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_sec_fund_adviser_crd ON sec_fund_adviser (adviser_crd);
"""

_UPSERT = """
INSERT INTO sec_fund_adviser
    (series_id, cik, adviser_name, adviser_crd, file_num, source, updated_at)
VALUES ($1, $2, $3, $4, $5, 'ncen', now())
ON CONFLICT (series_id) DO UPDATE SET
    cik = EXCLUDED.cik,
    adviser_name = EXCLUDED.adviser_name,
    adviser_crd = EXCLUDED.adviser_crd,
    file_num = EXCLUDED.file_num,
    source = 'ncen',
    updated_at = now()
"""


async def _ingest(dsn: str, rows: list[tuple], dry_run: bool) -> None:
    if dry_run:
        print(f"[dry-run] would upsert {len(rows)} series")
        return
    import asyncpg

    conn = await asyncpg.connect(dsn, ssl="require")
    try:
        await conn.execute(_DDL)
        for i in range(0, len(rows), 1000):
            await conn.executemany(_UPSERT, rows[i:i + 1000])
        n = await conn.fetchval("SELECT count(*) FROM sec_fund_adviser")
        with_crd = await conn.fetchval(
            "SELECT count(*) FROM sec_fund_adviser WHERE adviser_crd IS NOT NULL"
        )
        print(f"sec_fund_adviser rows: {n} (with CRD: {with_crd})")
    finally:
        await conn.close()


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--ncen-root", required=True)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    advisers = resolve_primary_advisers(Path(args.ncen_root))
    rows = [
        (sid, v["cik"], v["adviser_name"], v["crd"], v["file_num"])
        for sid, v in advisers.items()
    ]
    print(f"resolved {len(rows)} primary advisers")
    dsn = os.environ.get("NCEN_DSN", "")
    if not dsn and not args.dry_run:
        raise SystemExit("NCEN_DSN env var required (or use --dry-run)")
    asyncio.run(_ingest(dsn, rows, args.dry_run))


if __name__ == "__main__":
    main()
