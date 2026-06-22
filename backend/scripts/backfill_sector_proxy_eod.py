"""Backfill full Tiingo EOD history for sector/thematic proxy ETFs.

Run from backend/:
    uv run python scripts/backfill_sector_proxy_eod.py --dry-run
    uv run python scripts/backfill_sector_proxy_eod.py

Intentionally narrow: it ONLY writes raw rows into ``eod_prices`` and then
refreshes the ``cagg_eod_daily`` continuous aggregate over the covered range.
Unlike ``backfill_benchmark_proxy_etfs.py`` it does NOT create catalog rows
(instruments / instruments_universe / instrument_identity) nor NAV proxies —
these tickers are market-data references, not catalog funds.
"""

from __future__ import annotations

import argparse
import asyncio
import datetime as dt
import logging
import os
import pathlib
import sys
from collections.abc import Iterable

import asyncpg

# Ensure the backend root (parent of scripts/) is on sys.path so `app` is importable
_BACKEND_ROOT = pathlib.Path(__file__).parent.parent
if str(_BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(_BACKEND_ROOT))

from app.core.config import get_settings  # noqa: E402
from app.tiingo.client import TiingoClient  # noqa: E402
from app.tiingo.models import TiingoEodRow, TiingoTickerMeta  # noqa: E402
from app.tiingo.rate_limiter import TokenBucketLimiter  # noqa: E402

LOGGER = logging.getLogger(__name__)

EOD_CHUNK_SIZE = 1500
CAGG_VIEW = "cagg_eod_daily"

# Sector SPDRs + thematic/sector proxies requested for the macro-factor / rotation work.
TICKERS: tuple[str, ...] = (
    "XLE", "XLV", "XLF", "XLI", "XLB", "XLP", "XLU", "XLC", "XLY",
    "GUNR", "IFRA", "IBB", "ICLN", "EQL", "PFF",
)


def _database_url(env_name: str) -> str:
    settings = get_settings()
    if env_name == "DATABASE_URL":
        url = settings.database_url
    else:
        url = os.environ.get(env_name) or getattr(settings, env_name.lower(), None)
    if not url:
        raise RuntimeError(f"{env_name} is not configured.")
    return (
        url.replace("postgresql+asyncpg://", "postgresql://")
        .replace("postgres+asyncpg://", "postgres://")
        .replace("postgresql+psycopg://", "postgresql://")
        .replace("postgres+psycopg://", "postgres://")
        .replace("postgresql+psycopg2://", "postgresql://")
        .replace("postgres+psycopg2://", "postgres://")
    )


def _chunks[T](items: list[T], size: int) -> Iterable[list[T]]:
    for start in range(0, len(items), size):
        yield items[start : start + size]


async def _upsert_instrument_base(
    conn: asyncpg.Connection, ticker: str, meta: TiingoTickerMeta
) -> None:
    """Minimal row in ``instruments`` to satisfy the eod_prices FK.

    Deliberately scoped to the base instruments table only — no catalog
    (instruments_universe / instrument_identity) nor NAV writes.
    """
    await conn.execute(
        """
        INSERT INTO instruments (
            ticker, name, exchange_code, asset_type,
            tiingo_start_date, tiingo_end_date, eod_last_fetched_at, updated_at
        )
        VALUES ($1, $2, $3, 'etf', $4, $5, now(), now())
        ON CONFLICT (ticker) DO UPDATE SET
            name = COALESCE(EXCLUDED.name, instruments.name),
            exchange_code = COALESCE(EXCLUDED.exchange_code, instruments.exchange_code),
            asset_type = COALESCE(instruments.asset_type, EXCLUDED.asset_type),
            tiingo_start_date = EXCLUDED.tiingo_start_date,
            tiingo_end_date = EXCLUDED.tiingo_end_date,
            eod_last_fetched_at = now(),
            updated_at = now()
        """,
        ticker,
        meta.name or ticker,
        meta.exchange_code,
        meta.start_date,
        meta.end_date,
    )


async def _upsert_eod_rows(conn: asyncpg.Connection, rows: list[TiingoEodRow]) -> int:
    if not rows:
        return 0
    payload = [
        (
            row.ticker,
            row.date,
            row.open,
            row.high,
            row.low,
            row.close,
            row.volume,
            row.adj_open,
            row.adj_high,
            row.adj_low,
            row.adj_close,
            row.adj_volume,
            row.div_cash,
            row.split_factor,
        )
        for row in rows
    ]
    total = 0
    for chunk in _chunks(payload, EOD_CHUNK_SIZE):
        await conn.executemany(
            """
            INSERT INTO eod_prices (
                ticker, date, open, high, low, close, volume,
                adj_open, adj_high, adj_low, adj_close, adj_volume,
                div_cash, split_factor
            )
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13, $14)
            ON CONFLICT (ticker, date) DO UPDATE SET
                open = EXCLUDED.open,
                high = EXCLUDED.high,
                low = EXCLUDED.low,
                close = EXCLUDED.close,
                volume = EXCLUDED.volume,
                adj_open = EXCLUDED.adj_open,
                adj_high = EXCLUDED.adj_high,
                adj_low = EXCLUDED.adj_low,
                adj_close = EXCLUDED.adj_close,
                adj_volume = EXCLUDED.adj_volume,
                div_cash = EXCLUDED.div_cash,
                split_factor = EXCLUDED.split_factor
            """,
            chunk,
        )
        total += len(chunk)
    return total


async def _run(args: argparse.Namespace) -> None:
    settings = get_settings()
    token = settings.tiingo_token or os.environ.get("TIINGO_API_KEY")
    if not token:
        raise RuntimeError("TIINGO_TOKEN or TIINGO_API_KEY is required.")

    if args.tickers:
        wanted = {t.strip().upper() for t in args.tickers.split(",") if t.strip()}
        tickers = [t for t in TICKERS if t in wanted]
    else:
        tickers = list(TICKERS)
    if not tickers:
        raise RuntimeError("No tickers selected.")

    limiter = TokenBucketLimiter(
        rate_per_sec=settings.tiingo_rate_per_sec,
        burst=settings.tiingo_burst,
        hourly_cap=settings.tiingo_hourly_cap,
        daily_cap=settings.tiingo_daily_cap,
    )
    conn = await asyncpg.connect(_database_url(args.database_url_env), timeout=20)
    client = TiingoClient(
        token=token,
        limiter=limiter,
        base_url=settings.tiingo_base_url,
        timeout=settings.tiingo_timeout_seconds,
        max_retries=settings.tiingo_max_retries,
    )

    global_min: dt.date | None = None
    global_max: dt.date | None = None
    total_written = 0
    failures: list[str] = []
    try:
        for index, ticker in enumerate(tickers, start=1):
            n = len(tickers)
            LOGGER.info("[%d/%d] Fetching Tiingo metadata for %s", index, n, ticker)
            meta = await client.get_ticker_meta(ticker)
            start = meta.start_date or dt.date(1990, 1, 1)
            end = meta.end_date or dt.date.today()
            LOGGER.info("[%d/%d] Fetching %s prices %s -> %s", index, n, ticker, start, end)
            rows = await client.get_eod_prices(ticker, start, end)
            if not rows:
                LOGGER.warning("[%d/%d] %s: Tiingo returned 0 rows — skipping", index, n, ticker)
                failures.append(ticker)
                continue

            first = min(row.date for row in rows)
            last = max(row.date for row in rows)
            global_min = first if global_min is None else min(global_min, first)
            global_max = last if global_max is None else max(global_max, last)

            if args.dry_run:
                LOGGER.info(
                    "[%d/%d] DRY RUN %s: name=%r rows=%d first=%s last=%s",
                    index, len(tickers), ticker, meta.name, len(rows), first, last,
                )
                continue

            async with conn.transaction():
                await _upsert_instrument_base(conn, ticker, meta)
                written = await _upsert_eod_rows(conn, rows)
            total_written += written
            LOGGER.info(
                "[%d/%d] %s written: eod_rows=%d first=%s last=%s",
                index, len(tickers), ticker, written, first, last,
            )

        if args.dry_run:
            LOGGER.info("DRY RUN complete: covered range %s -> %s", global_min, global_max)
            return

        if global_min is not None and global_max is not None:
            # Refresh the continuous aggregate over the full covered span. The
            # window must be open-ended past the last bucket; +1 day suffices for
            # the 1-day bucket. refresh_continuous_aggregate manages its own
            # transactions, so it must run outside an explicit transaction block.
            win_start = global_min.isoformat()
            win_end = (global_max + dt.timedelta(days=1)).isoformat()
            LOGGER.info("Refreshing %s over [%s, %s)", CAGG_VIEW, win_start, win_end)
            await conn.execute(
                f"CALL refresh_continuous_aggregate('{CAGG_VIEW}', '{win_start}', '{win_end}')"
            )
            LOGGER.info("Continuous aggregate refresh complete.")

        LOGGER.info(
            "DONE: %d tickers, %d eod rows written. Failures: %s",
            len(tickers) - len(failures), total_written, failures or "none",
        )
    finally:
        await client.aclose()
        await conn.close()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--database-url-env",
        default="DATALAKE_DB_URL",
        help="Environment variable containing the target Postgres URL.",
    )
    parser.add_argument("--tickers", default=None, help="Comma-separated explicit ticker subset.")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Fetch Tiingo metadata/prices but do not write to the database.",
    )
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    asyncio.run(_run(args))


if __name__ == "__main__":
    main()
