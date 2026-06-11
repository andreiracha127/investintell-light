"""Compute the screener_metrics cross-sectional snapshot (F6.3).

Run from backend/:
    uv run python scripts/compute_screener_metrics.py
    uv run python scripts/compute_screener_metrics.py --tickers AAPL,MSFT
    uv run python scripts/compute_screener_metrics.py --batch-size 100

Batch path: reads local EOD prices + fundamentals_snapshot and upserts one
metrics row per active universe constituent. Requires TIINGO_TOKEN only to
refresh the five benchmark ETFs (SPY/GLD/AGG/TLT/USO) at job start; the
metric computation itself is fully local.
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
from app.sync.metrics import DEFAULT_BATCH_SIZE, run_metrics  # noqa: E402


async def _run(tickers: list[str] | None, batch_size: int) -> None:
    client = provider.get_client()
    try:
        async with AsyncSessionLocal() as session:
            report = await run_metrics(
                session, client, tickers=tickers, batch_size=batch_size
            )
    finally:
        await provider.aclose()
        await engine.dispose()

    print()
    print("=== Screener metrics report ===")
    for line in report.lines():
        print(line)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--tickers",
        type=str,
        default=None,
        help="Comma-separated explicit ticker subset (testing), e.g. AAPL,MSFT.",
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=DEFAULT_BATCH_SIZE,
        help="Tickers loaded per EOD SELECT (memory bound).",
    )
    args = parser.parse_args()

    tickers = args.tickers.split(",") if args.tickers else None

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    asyncio.run(_run(tickers, args.batch_size))


if __name__ == "__main__":
    main()
