"""Backfill Tiingo EOD prices for the active screener universe (F6.2).

Run from backend/:
    uv run python scripts/backfill_universe_eod.py
    uv run python scripts/backfill_universe_eod.py --limit 25
    uv run python scripts/backfill_universe_eod.py --tickers AAPL,MSFT

Batch path: bypasses the per-request cold-ticker cap (that cap protects
interactive latency); the token-bucket rate limiter still governs every
Tiingo request.  Requires TIINGO_TOKEN and a populated universe_constituents
table (run scripts/sync_universe.py first).
"""

import argparse
import asyncio
import logging
import pathlib
import sys

# Ensure the backend root (parent of scripts/) is on sys.path so `app` is importable
# when running as a plain script rather than an installed package.
_BACKEND_ROOT = pathlib.Path(__file__).parent.parent
if str(_BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(_BACKEND_ROOT))

from app.core.db import AsyncSessionLocal, engine  # noqa: E402
from app.core.tiingo_provider import provider  # noqa: E402
from app.sync.backfill import run_backfill  # noqa: E402


async def _run(limit: int | None, tickers: list[str] | None) -> None:
    client = provider.get_client()
    try:
        async with AsyncSessionLocal() as session:
            report = await run_backfill(session, client, limit=limit, tickers=tickers)
    finally:
        await provider.aclose()
        await engine.dispose()

    print()
    print("=== Universe EOD backfill report ===")
    for line in report.lines():
        print(line)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Process at most N constituents (testing).",
    )
    parser.add_argument(
        "--tickers",
        type=str,
        default=None,
        help="Comma-separated explicit ticker subset (testing), e.g. AAPL,MSFT.",
    )
    args = parser.parse_args()

    tickers = args.tickers.split(",") if args.tickers else None

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    asyncio.run(_run(args.limit, tickers))


if __name__ == "__main__":
    main()
