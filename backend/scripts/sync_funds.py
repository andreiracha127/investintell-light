"""Sync the fund universe from the mother DB (F8.1).

Run from backend/:
    uv run python scripts/sync_funds.py
    uv run python scripts/sync_funds.py --limit 50
    uv run python scripts/sync_funds.py --dry-run

Read-only against the mother DB (one asyncpg connection per run, DSN never
logged); idempotent upserts into the local funds / fund_risk_latest /
fund_nav / fund_holdings tables — re-running only refreshes (resumable:
NAV and holdings batches commit independently).  Requires
INVESTINTELL_DB_URL and migration 0006 applied locally.
"""

import argparse
import asyncio
import logging
import pathlib
import sys
import time

# Ensure the backend root (parent of scripts/) is on sys.path so `app` is importable
# when running as a plain script rather than an installed package.
_BACKEND_ROOT = pathlib.Path(__file__).parent.parent
if str(_BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(_BACKEND_ROOT))

from app.core.db import engine  # noqa: E402
from app.sync.funds import run_sync  # noqa: E402


async def _run(limit: int | None, dry_run: bool) -> None:
    started = time.monotonic()
    try:
        report = await run_sync(limit=limit, dry_run=dry_run)
    finally:
        await engine.dispose()
    elapsed = time.monotonic() - started

    print()
    print("=== Fund sync report (F8.1) ===")
    for line in report.lines():
        print(line)
    print(f"Total time:                         {elapsed:.1f}s")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Process at most N eligible funds (testing).",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Only compute the eligible-fund count; no local writes.",
    )
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    asyncio.run(_run(args.limit, args.dry_run))


if __name__ == "__main__":
    main()
