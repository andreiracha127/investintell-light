"""On-demand-with-cache EOD ingestion service.

The single sanctioned cold path to Tiingo: routes call ``ensure_eod_data``,
which decides per ticker whether the cache (TimescaleDB) is fresh or whether a
synchronous fetch through ``TiingoClient`` is required, then upserts
idempotently on (ticker, date).

Transaction semantics (documented, deliberate): tickers are processed
SEQUENTIALLY with one commit per ticker.  If ticker N fails, its work is
rolled back and the typed error re-raised — tickers 1..N-1 stay committed.
A bad ticker therefore never destroys the others' ingested data, and the
caller still sees a loud failure.

Fetch-window policy:
- Brand-new ticker (no price rows in DB): fetch the FULL available history
  (Tiingo's startDate for the ticker, floored at 1990-01-01) so subsequent
  windows are served from the DB without further Tiingo calls.
- Stale existing ticker: fetch incrementally from max(date) in DB minus a
  7-day overlap (captures late Tiingo corrections) through today.
The caller's requested [start, end] window is intentionally NOT used to bound
the fetch — the cache is filled wide once, then read narrow forever.

Concurrent cold-fetch window: two simultaneous requests for the same cold
ticker may both reach Tiingo and attempt to upsert the same rows; ON CONFLICT
DO UPDATE keeps the DB correct (last writer wins on each row).
TODO: add a per-ticker asyncio.Lock to collapse the redundant Tiingo fetch.
"""

import datetime as dt
from dataclasses import dataclass, field
from typing import Literal

from sqlalchemy import func, select, update
from sqlalchemy.dialects.postgresql import Insert as PgInsert
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql.dml import Update

from app.core.config import get_settings
from app.models.eod_price import EodPrice
from app.models.instrument import Instrument
from app.tiingo.client import TiingoClient
from app.tiingo.models import TiingoEodRow, TiingoTickerMeta

# Floor for full-history fetches when Tiingo reports no startDate for a ticker.
HISTORY_FLOOR = dt.date(1990, 1, 1)
# Overlap window for incremental fetches — re-fetches the last N days already
# in the DB so late corrections from Tiingo overwrite stale rows via upsert.
INCREMENTAL_OVERLAP_DAYS = 7

# All mutable price columns of eod_prices — everything except the (ticker, date) PK.
_EOD_PRICE_COLUMNS = (
    "open",
    "high",
    "low",
    "close",
    "volume",
    "adj_open",
    "adj_high",
    "adj_low",
    "adj_close",
    "adj_volume",
    "div_cash",
    "split_factor",
)

# asyncpg hard-limits query parameters to 32 767 (INT16_MAX).  Each EOD row
# binds 14 parameters (2 PK columns + 12 price columns).  2000 rows × 14 = 28 000,
# safely under the ceiling with room for future column additions.
_EOD_UPSERT_CHUNK = 2000

TickerAction = Literal["fresh", "fetched_full", "fetched_incremental"]


class ColdTickerCapExceededError(Exception):
    """Raised when a request would ingest more truly-cold tickers than allowed.

    "Cold" means no instrument row exists in the DB — a full-history fetch
    against Tiingo is required.  Stale tickers (instrument row exists but
    eod_last_fetched_at is outside the freshness window) need only one
    incremental request each and are never capped.

    Fail loud: the service never silently ingests a subset.  Routes map this
    to HTTP 422.
    """


@dataclass
class TickerOutcome:
    """Per-ticker result of ``ensure_eod_data``."""

    ticker: str
    action: TickerAction
    rows_upserted: int = 0


@dataclass
class EnsureReport:
    """Aggregate result of one ``ensure_eod_data`` call (input order preserved)."""

    outcomes: list[TickerOutcome] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Pure decision helpers (unit-tested directly — no session mocking required)
# ---------------------------------------------------------------------------


def normalize_tickers(tickers: list[str]) -> list[str]:
    """Uppercase, strip, dedupe — preserving first-seen order."""
    seen: set[str] = set()
    out: list[str] = []
    for raw in tickers:
        ticker = raw.strip().upper()
        if ticker and ticker not in seen:
            seen.add(ticker)
            out.append(ticker)
    return out


def is_fresh(
    eod_last_fetched_at: dt.datetime | None,
    now: dt.datetime,
    staleness_hours: float,
) -> bool:
    """True if the last successful EOD fetch is within the staleness window."""
    if eod_last_fetched_at is None:
        return False
    return now - eod_last_fetched_at <= dt.timedelta(hours=staleness_hours)


def classify_tickers(
    tickers: list[str],
    instruments: dict[str, Instrument],
    now: dt.datetime,
    staleness_hours: float,
) -> tuple[list[str], list[str], list[str]]:
    """Split *tickers* into (fresh, stale, cold), preserving order.

    - fresh: instrument row exists AND eod_last_fetched_at is within the window.
             No Tiingo call needed.
    - stale: instrument row exists BUT eod_last_fetched_at is outside the window
             (or None).  Needs one incremental Tiingo fetch.
    - cold:  no instrument row at all — needs a full-history Tiingo fetch.

    Proxy safety: the per-ticker commit that finalises each ingest (instrument
    upsert + EOD rows + mark-fetched) is atomic, so "instrument row exists" is a
    reliable proxy for "a prior full ingest completed successfully".  A partial
    failure on a previous request rolls back before writing the instrument row,
    so such tickers remain in the cold bucket on retry.

    Only the cold bucket is subject to ``max_cold_tickers_per_request``.
    Stale tickers always refresh (bounded by upstream position-count caps and
    the Tiingo rate limiter — no additional cap required).
    """
    fresh: list[str] = []
    stale: list[str] = []
    cold: list[str] = []
    for ticker in tickers:
        instrument = instruments.get(ticker)
        if instrument is None:
            cold.append(ticker)
        elif is_fresh(instrument.eod_last_fetched_at, now, staleness_hours):
            fresh.append(ticker)
        else:
            stale.append(ticker)
    return fresh, stale, cold


def incremental_start(max_date_in_db: dt.date) -> dt.date:
    """Start date for an incremental fetch: overlap to capture Tiingo corrections."""
    return max_date_in_db - dt.timedelta(days=INCREMENTAL_OVERLAP_DAYS)


def full_history_start(tiingo_start_date: dt.date | None) -> dt.date:
    """Start date for a full-history fetch: Tiingo's startDate, or the 1990 floor
    when Tiingo does not report one."""
    return tiingo_start_date or HISTORY_FLOOR


# ---------------------------------------------------------------------------
# Statement builders (compiled-SQL-tested — no session mocking required)
# ---------------------------------------------------------------------------


def build_instrument_upsert(meta: TiingoTickerMeta) -> PgInsert:
    """INSERT ... ON CONFLICT (ticker) DO UPDATE for the instruments table.

    CRITICAL: this is a Core statement, so Instrument.updated_at's
    ``onupdate=func.now()`` does NOT fire — ``updated_at`` MUST be (and is)
    set explicitly in the ``set_`` clause.
    """
    stmt = pg_insert(Instrument).values(
        ticker=meta.ticker,
        name=meta.name,
        exchange_code=meta.exchange_code,
        tiingo_start_date=meta.start_date,
        tiingo_end_date=meta.end_date,
    )
    return stmt.on_conflict_do_update(
        index_elements=[Instrument.ticker],
        set_={
            "name": stmt.excluded.name,
            "exchange_code": stmt.excluded.exchange_code,
            "tiingo_start_date": stmt.excluded.tiingo_start_date,
            "tiingo_end_date": stmt.excluded.tiingo_end_date,
            "updated_at": func.now(),
        },
    )


def build_eod_upsert(rows: list[TiingoEodRow]) -> PgInsert:
    """Single bulk INSERT ... ON CONFLICT (ticker, date) DO UPDATE for eod_prices.

    Idempotent: re-running with the same rows never duplicates; conflicting
    rows get all price fields overwritten with the fresh Tiingo values.
    """
    if not rows:
        raise ValueError("build_eod_upsert requires at least one row")
    values = [
        {"ticker": row.ticker, "date": row.date}
        | {col: getattr(row, col) for col in _EOD_PRICE_COLUMNS}
        for row in rows
    ]
    stmt = pg_insert(EodPrice).values(values)
    return stmt.on_conflict_do_update(
        index_elements=[EodPrice.ticker, EodPrice.date],
        set_={col: getattr(stmt.excluded, col) for col in _EOD_PRICE_COLUMNS},
    )


def build_mark_fetched(ticker: str) -> Update:
    """UPDATE instruments SET eod_last_fetched_at = now() after a successful ingest.

    Core update — ``updated_at`` must be set explicitly (see Instrument model note).
    """
    return (
        update(Instrument)
        .where(Instrument.ticker == ticker)
        .values(eod_last_fetched_at=func.now(), updated_at=func.now())
    )


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


async def ensure_eod_data(
    session: AsyncSession,
    client: TiingoClient,
    tickers: list[str],
    start: dt.date,
    end: dt.date,
    *,
    staleness_hours: float | None = None,
    max_cold_tickers: int | None = None,
) -> EnsureReport:
    """Guarantee EOD data for *tickers* is present and fresh in the DB.

    Args:
        session: Async DB session (transaction boundaries managed here —
            one commit per successfully ingested ticker, see module docstring).
        client: The shared TiingoClient (only used for cold/stale tickers).
        tickers: Requested tickers (normalized: uppercased, deduped, order kept).
        start: Requested window start (informational — see fetch-window policy).
        end: Requested window end (informational — see fetch-window policy).
        staleness_hours: Override for tests; defaults to settings.
        max_cold_tickers: Override for tests; defaults to settings.

    Raises:
        ColdTickerCapExceededError: More than ``max_cold_tickers`` new tickers
            (no instrument row) in a single request.  Previously-ingested
            tickers that are merely stale always refresh incrementally without
            cap.
        TiingoError subclasses: Propagated from the client (fail loud).
    """
    settings = get_settings()
    if staleness_hours is None:
        staleness_hours = settings.eod_staleness_hours
    if max_cold_tickers is None:
        max_cold_tickers = settings.max_cold_tickers_per_request

    ordered = normalize_tickers(tickers)

    result = await session.execute(
        select(Instrument).where(Instrument.ticker.in_(ordered))
    )
    instruments = {inst.ticker: inst for inst in result.scalars().all()}

    now = dt.datetime.now(dt.UTC)
    _fresh, _stale, cold = classify_tickers(ordered, instruments, now, staleness_hours)
    if len(cold) > max_cold_tickers:
        raise ColdTickerCapExceededError(
            f"Request needs a full-history fetch for {len(cold)} new tickers "
            f"({', '.join(cold)}) but at most {max_cold_tickers} new tickers per "
            "request are allowed. Previously-ingested tickers refresh without cap."
        )

    # Tickers that need a Tiingo fetch: cold (full history) + stale (incremental).
    # Fresh tickers are skipped entirely.
    needs_fetch: set[str] = set(cold) | set(_stale)
    today = dt.date.today()
    report = EnsureReport()

    for ticker in ordered:
        if ticker not in needs_fetch:
            report.outcomes.append(TickerOutcome(ticker=ticker, action="fresh"))
            continue

        try:
            # 1. Validate the ticker exists on Tiingo (404 propagates as
            #    TiingoNotFoundError) and upsert instrument metadata.
            meta = await client.get_ticker_meta(ticker)
            await session.execute(build_instrument_upsert(meta))

            # 2. Decide the fetch window: incremental if we already hold rows,
            #    full available history otherwise.
            max_date = await session.scalar(
                select(func.max(EodPrice.date)).where(EodPrice.ticker == ticker)
            )
            action: TickerAction
            if max_date is not None:
                fetch_start = incremental_start(max_date)
                action = "fetched_incremental"
            else:
                fetch_start = full_history_start(meta.start_date)
                action = "fetched_full"

            # 3. Fetch and bulk-upsert prices, then mark the instrument fetched.
            #    asyncpg caps query parameters at 32 767; chunk the rows so each
            #    execute call stays well under that limit (_EOD_UPSERT_CHUNK rows
            #    × 14 params/row = 28 000 params, safely below the ceiling).
            #    All chunks are executed within the same transaction; the single
            #    commit below atomically finalises the whole ticker.
            rows = await client.get_eod_prices(ticker, fetch_start, today)
            for chunk_start in range(0, len(rows), _EOD_UPSERT_CHUNK):
                chunk = rows[chunk_start : chunk_start + _EOD_UPSERT_CHUNK]
                await session.execute(build_eod_upsert(chunk))
            await session.execute(build_mark_fetched(ticker))
            await session.commit()
        except Exception:
            # Roll back only this ticker's work; earlier tickers stay committed.
            await session.rollback()
            raise

        report.outcomes.append(
            TickerOutcome(ticker=ticker, action=action, rows_upserted=len(rows))
        )

    return report
