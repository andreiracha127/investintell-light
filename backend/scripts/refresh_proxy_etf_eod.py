"""Daily EOD refresh for curated proxy/benchmark ETFs (sector rotation work).

Run from backend/:
    uv run python scripts/refresh_proxy_etf_eod.py
    uv run python scripts/refresh_proxy_etf_eod.py --tickers XLE,XLF

Intended as a daily cron (alongside the universe warmer). Keeps the curated
``app.sync.proxy_etf.PROXY_ETF_TICKERS`` fresh in ``eod_prices`` via the same
incremental per-ticker ingest used by the request path. The cagg_eod_daily
continuous aggregate refreshes itself via its TimescaleDB policy.

Writes to DATABASE_URL — in production (Railway) this is the Tiger data-lake;
the token-bucket rate limiter inside TiingoClient governs every request.
"""

import argparse
import asyncio
import logging
import pathlib
import sys

# Ensure the backend root (parent of scripts/) is on sys.path so `app` is importable
_BACKEND_ROOT = pathlib.Path(__file__).parent.parent
if str(_BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(_BACKEND_ROOT))

from app.core.db import AsyncSessionLocal, engine  # noqa: E402
from app.core.tiingo_provider import provider  # noqa: E402
from app.sync.proxy_etf import run_proxy_etf_backfill  # noqa: E402


async def _run(tickers: list[str] | None) -> None:
    client = provider.get_client()
    try:
        async with AsyncSessionLocal() as session:
            report = await run_proxy_etf_backfill(session, client, tickers=tickers)
    finally:
        await provider.aclose()
        await engine.dispose()

    print()
    print("=== Proxy-ETF EOD refresh report ===")
    for line in report.lines():
        print(line)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--tickers",
        type=str,
        default=None,
        help="Comma-separated explicit subset (defaults to PROXY_ETF_TICKERS).",
    )
    args = parser.parse_args()
    tickers = args.tickers.split(",") if args.tickers else None

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    asyncio.run(_run(tickers))


if __name__ == "__main__":
    main()
