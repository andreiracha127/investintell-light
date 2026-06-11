"""Universe EOD backfill (F6.2): batch-ingest Tiingo prices for the universe.

Iterates universe_constituents WHERE status='active' and runs the SAME
per-ticker ingest used by the request path (``ingest_one_ticker``) — minus the
per-request cold-ticker cap, which exists to protect interactive latency and
does not apply to a batch.  The token-bucket rate limiter inside TiingoClient
still governs every single request.

Failure policy (batch tolerates per-ticker failures, fails loud per item):
- TiingoNotFoundError  → constituent marked status='no_tiingo_data', continue.
- Other TiingoError    → queued and retried ONCE at the end of the run;
                          a second failure is recorded in the report.
- Any other exception  → recorded in the report, batch continues.

Run via scripts/backfill_universe_eod.py — never from any request path.
"""

import datetime as dt
import logging
import time
from dataclasses import dataclass, field

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql.dml import Update

from app.core.config import get_settings
from app.ingestion.service import ingest_one_ticker, is_fresh
from app.models.eod_price import EodPrice
from app.models.instrument import Instrument
from app.models.universe import UniverseConstituent
from app.tiingo.client import TiingoClient
from app.tiingo.exceptions import TiingoError, TiingoNotFoundError

logger = logging.getLogger(__name__)

PROGRESS_EVERY = 50


@dataclass
class BackfillReport:
    """Outcome counts for one backfill run."""

    total_considered: int = 0
    ingested_full: int = 0
    ingested_incremental: int = 0
    skipped_fresh: int = 0
    not_found: int = 0
    recovered_on_retry: int = 0
    errors: dict[str, str] = field(default_factory=dict)
    eod_price_rows_total: int | None = None

    def lines(self) -> list[str]:
        out = [
            f"Tickers considered:        {self.total_considered}",
            f"  ingested (full history): {self.ingested_full}",
            f"  ingested (incremental):  {self.ingested_incremental}",
            f"  skipped (fresh):         {self.skipped_fresh}",
            f"  not found on Tiingo:     {self.not_found} (marked no_tiingo_data)",
            f"  recovered on retry:      {self.recovered_on_retry}",
            f"  errors:                  {len(self.errors)}",
        ]
        for ticker, msg in sorted(self.errors.items()):
            out.append(f"    {ticker}: {msg}")
        if self.eod_price_rows_total is not None:
            out.append(f"eod_prices total rows:     {self.eod_price_rows_total}")
        return out


def build_mark_no_tiingo_data(ticker: str) -> Update:
    """UPDATE universe_constituents SET status='no_tiingo_data' for one ticker."""
    return (
        update(UniverseConstituent)
        .where(UniverseConstituent.ticker == ticker)
        .values(status="no_tiingo_data")
    )


async def _mark_no_tiingo_data(session: AsyncSession, ticker: str) -> None:
    await session.execute(build_mark_no_tiingo_data(ticker))
    await session.commit()


async def _try_ingest(
    session: AsyncSession,
    client: TiingoClient,
    ticker: str,
    today: dt.date,
    report: BackfillReport,
) -> str | None:
    """Ingest one ticker, mapping outcomes into the report.

    Returns the ticker if it should be queued for the end-of-run retry
    (transient Tiingo error), else None.  Never raises: the batch tolerates
    per-ticker failures, each recorded loudly.
    """
    try:
        outcome = await ingest_one_ticker(session, client, ticker, today)
    except TiingoNotFoundError:
        await _mark_no_tiingo_data(session, ticker)
        report.not_found += 1
        logger.warning("%s: not found on Tiingo — marked no_tiingo_data", ticker)
        return None
    except TiingoError as exc:
        logger.warning("%s: Tiingo error (%s) — queued for retry", ticker, exc)
        report.errors[ticker] = f"{type(exc).__name__}: {exc}"
        return ticker
    except Exception as exc:  # noqa: BLE001 — batch must survive any one ticker
        logger.exception("%s: unexpected error — batch continues", ticker)
        report.errors[ticker] = f"{type(exc).__name__}: {exc}"
        return None

    if outcome.action == "fetched_full":
        report.ingested_full += 1
    else:
        report.ingested_incremental += 1
    return None


async def run_backfill(
    session: AsyncSession,
    client: TiingoClient,
    *,
    limit: int | None = None,
    tickers: list[str] | None = None,
    staleness_hours: float | None = None,
) -> BackfillReport:
    """Backfill EOD prices for all active universe constituents.

    Args:
        session: Async DB session (per-ticker commit semantics live inside
            ``ingest_one_ticker``; status marks commit immediately too).
        client: The shared TiingoClient (rate limiter governs every request).
        limit: Optional cap on the number of tickers processed (testing).
        tickers: Optional explicit subset (testing); normalized to uppercase.
        staleness_hours: Freshness window override; defaults to settings —
            tickers fetched within the window are skipped, so re-running the
            backfill is cheap and idempotent.
    """
    if staleness_hours is None:
        staleness_hours = get_settings().eod_staleness_hours

    stmt = (
        select(UniverseConstituent.ticker)
        .where(UniverseConstituent.status == "active")
        .order_by(UniverseConstituent.ticker)
    )
    if tickers:
        wanted = [t.strip().upper() for t in tickers if t.strip()]
        stmt = stmt.where(UniverseConstituent.ticker.in_(wanted))
    if limit is not None:
        stmt = stmt.limit(limit)
    result = await session.execute(stmt)
    todo: list[str] = list(result.scalars().all())

    report = BackfillReport(total_considered=len(todo))
    logger.info("Backfill: %d active constituents to process", len(todo))

    today = dt.date.today()
    retry_queue: list[str] = []
    started = time.monotonic()

    for i, ticker in enumerate(todo, start=1):
        # Freshness check mirrors ensure_eod_data's classification: an
        # instrument fetched within the staleness window needs no Tiingo call.
        instrument = await session.get(Instrument, ticker)
        now = dt.datetime.now(dt.UTC)
        if instrument is not None and is_fresh(
            instrument.eod_last_fetched_at, now, staleness_hours
        ):
            report.skipped_fresh += 1
        else:
            queued = await _try_ingest(session, client, ticker, today, report)
            if queued is not None:
                retry_queue.append(queued)

        if i % PROGRESS_EVERY == 0 or i == len(todo):
            elapsed = time.monotonic() - started
            rate = i / elapsed if elapsed > 0 else 0.0
            eta = (len(todo) - i) / rate if rate > 0 else float("inf")
            print(
                f"[backfill] {i}/{len(todo)} tickers — {elapsed:.0f}s elapsed, "
                f"{rate:.2f}/s, ETA {eta:.0f}s",
                flush=True,
            )

    # One retry pass for transient Tiingo errors (rate-limit/5xx).  A retry
    # that succeeds clears the recorded first-pass error; a second failure
    # (of any kind) keeps/overwrites the error entry.
    for ticker in retry_queue:
        logger.info("%s: retrying after transient Tiingo error", ticker)
        try:
            outcome = await ingest_one_ticker(session, client, ticker, today)
        except TiingoNotFoundError:
            await _mark_no_tiingo_data(session, ticker)
            report.not_found += 1
            del report.errors[ticker]
            logger.warning("%s: not found on retry — marked no_tiingo_data", ticker)
            continue
        except Exception as exc:  # noqa: BLE001 — batch must survive any one ticker
            report.errors[ticker] = f"retry failed — {type(exc).__name__}: {exc}"
            logger.warning("%s: retry failed (%s)", ticker, exc)
            continue
        del report.errors[ticker]
        report.recovered_on_retry += 1
        if outcome.action == "fetched_full":
            report.ingested_full += 1
        else:
            report.ingested_incremental += 1

    report.eod_price_rows_total = await session.scalar(
        select(func.count()).select_from(EodPrice)
    )
    return report
