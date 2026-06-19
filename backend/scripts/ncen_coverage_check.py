"""Cross the N-CEN primary-adviser map against the light funds_list_mv universe.
Reports, per fund_type, how many funds would resolve a real adviser.

Usage (DSN via env):
    NCEN_DSN=postgresql://... python -m scripts.ncen_coverage_check --map ncen_advisers.json
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os


async def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--map", required=True)
    args = ap.parse_args()
    import asyncpg

    with open(args.map, encoding="utf-8") as fh:
        advisers: dict[str, dict] = json.load(fh)
    series_with_adviser = set(advisers)

    dsn = os.environ["NCEN_DSN"]
    conn = await asyncpg.connect(dsn, ssl="require")
    rows = await conn.fetch("SELECT series_id, fund_type FROM funds_list_mv")
    await conn.close()

    from collections import Counter
    total = Counter()
    resolved = Counter()
    for r in rows:
        ft = r["fund_type"]
        total[ft] += 1
        if r["series_id"] in series_with_adviser:
            resolved[ft] += 1

    print(f"{'fund_type':14} {'total':>7} {'resolved':>9} {'pct':>6}")
    for ft in sorted(total, key=lambda k: -total[k]):
        t, rsv = total[ft], resolved[ft]
        print(f"{ft:14} {t:>7} {rsv:>9} {100*rsv/t:>5.1f}%")
    print(f"{'ALL':14} {sum(total.values()):>7} {sum(resolved.values()):>9} "
          f"{100*sum(resolved.values())/sum(total.values()):>5.1f}%")


if __name__ == "__main__":
    asyncio.run(main())
