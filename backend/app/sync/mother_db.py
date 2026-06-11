"""Mother-DB sync: SEC ticker↔CIK crosswalk + fundamentals snapshot (F6.2).

Pipeline (one run = one `run_sync()` call, normally via scripts/sync_universe.py):

1. Download SEC company_tickers.json (official crosswalk; requires a
   User-Agent header with contact info) and save a dated snapshot under
   backend/seeds/ (versioned in git per dispatch §3.5).
2. Read the mother DB (READ-ONLY, asyncpg, connection opened per run and
   closed after): the "active" CIK set = CIKs whose latest
   company_characteristics_monthly period_end is within the last 12 months.
3. Universe = SEC ticker rows whose CIK is in the active set.  Tickers are
   normalized to uppercase; tickers with characters outside [A-Z0-9.-]
   (warrants/units suffixes) are excluded and counted.  Multiple share
   classes per CIK (e.g. GOOG/GOOGL) are kept — each is a tradable line.
4. Fetch the latest fundamentals row per active CIK (single query) and upsert
   universe_constituents + fundamentals_snapshot idempotently.

ABSOLUTE RULES honoured here:
- The mother DB is accessed ONLY by this module, never in any request path.
- The mother-DB DSN is NEVER logged or printed.
- All local writes are idempotent upserts (ON CONFLICT DO UPDATE).
"""

import datetime as dt
import json
import logging
import re
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import asyncpg
import httpx
from sqlalchemy.dialects.postgresql import Insert as PgInsert
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.chunks import chunked
from app.core.config import get_settings
from app.models.universe import FundamentalsSnapshot, UniverseConstituent

logger = logging.getLogger(__name__)

SEC_TICKERS_URL = "https://www.sec.gov/files/company_tickers.json"
# SEC requires a descriptive User-Agent with contact information.
SEC_USER_AGENT = "investintell-light admin@investintell.local"

# Provenance tag written to universe_constituents.source.
UNIVERSE_SOURCE = "sec_company_tickers+mother_ccm"

# Tickers must be plain US-equity symbols; anything else (warrant/unit/when-
# issued suffixes with ~, /, spaces, etc.) is excluded from the universe.
_TICKER_RE = re.compile(r"[A-Z0-9.\-]+")

# Chunk size for bulk upserts.  asyncpg caps query parameters at 32 767;
# fundamentals_snapshot binds 15 params/row → 1 000 rows = 15 000 params,
# universe_constituents binds 6 params/row → 6 000 params.  Both safe.
_UPSERT_CHUNK = 1000

# Active-CIK definition: latest fundamentals period_end within this window.
ACTIVE_CIKS_SQL = """
SELECT cik, max(period_end) AS latest_period_end
FROM company_characteristics_monthly
GROUP BY cik
HAVING max(period_end) >= (CURRENT_DATE - INTERVAL '12 months')
"""

# Latest fundamentals row per CIK (inventory doc §"Join de fundamentals").
FUNDAMENTALS_SQL = """
SELECT cik, period_end, book_equity, total_assets, net_income_ttm,
       revenue, gross_profit, shares_outstanding, quality_roa,
       investment_growth, profitability_gross, source_filing_date
FROM company_characteristics_monthly
WHERE cik = ANY($1)
  AND (cik, period_end) IN (SELECT cik, max(period_end)
                            FROM company_characteristics_monthly GROUP BY cik)
"""


@dataclass(frozen=True)
class SecTickerRow:
    """One row of the SEC company_tickers.json crosswalk (normalized)."""

    cik: int
    ticker: str
    title: str


@dataclass
class SyncReport:
    """Counts for one sync run (printed by the CLI and returned to callers)."""

    sec_rows: int = 0
    sec_excluded_invalid: int = 0
    active_ciks: int = 0
    matched_tickers: int = 0
    multi_class_ciks: int = 0
    fundamentals_rows: int = 0
    fundamentals_missing_ciks: int = 0
    universe_upserted: int = 0
    fundamentals_upserted: int = 0
    dry_run: bool = False

    def lines(self) -> list[str]:
        return [
            f"SEC crosswalk rows parsed:        {self.sec_rows}",
            f"  excluded (invalid ticker chars): {self.sec_excluded_invalid}",
            f"Mother-DB active CIKs (<=12mo):    {self.active_ciks}",
            f"Universe tickers matched by CIK:   {self.matched_tickers}",
            f"  CIKs with multiple share classes: {self.multi_class_ciks}",
            f"Fundamentals rows fetched:         {self.fundamentals_rows}",
            f"  active CIKs missing fundamentals: {self.fundamentals_missing_ciks}",
            f"universe_constituents upserted:    {self.universe_upserted}",
            f"fundamentals_snapshot upserted:    {self.fundamentals_upserted}",
            f"Dry run (no local writes):         {self.dry_run}",
        ]


# ---------------------------------------------------------------------------
# Pure helpers (unit-tested directly)
# ---------------------------------------------------------------------------


def parse_sec_company_tickers(raw: dict[str, Any]) -> list[SecTickerRow]:
    """Parse SEC company_tickers.json: {"0": {"cik_str", "ticker", "title"}, ...}.

    Normalizes tickers to stripped-uppercase and dedupes exact duplicate
    ticker symbols (first occurrence wins — the SEC file is ordered by
    market cap, so the primary listing comes first).  Multiple tickers per
    CIK (share classes) are all kept.
    """
    rows: list[SecTickerRow] = []
    seen: set[str] = set()
    for entry in raw.values():
        ticker = str(entry["ticker"]).strip().upper()
        if not ticker or ticker in seen:
            continue
        seen.add(ticker)
        rows.append(
            SecTickerRow(
                cik=int(entry["cik_str"]),
                ticker=ticker,
                title=str(entry.get("title") or "").strip(),
            )
        )
    return rows


def is_valid_universe_ticker(ticker: str) -> bool:
    """True for plain US-equity symbols: only [A-Z0-9.-] allowed."""
    return bool(_TICKER_RE.fullmatch(ticker))


def select_universe(
    sec_rows: list[SecTickerRow], active_ciks: set[int]
) -> tuple[list[SecTickerRow], int, int]:
    """Pick the universe: SEC rows whose CIK is active, valid tickers only.

    Returns (matched_rows, excluded_invalid_count, multi_class_cik_count).
    excluded_invalid_count counts only active-CIK candidates rejected for
    invalid ticker characters (warrants/units suffixes).
    """
    matched: list[SecTickerRow] = []
    excluded = 0
    for row in sec_rows:
        if row.cik not in active_ciks:
            continue
        if not is_valid_universe_ticker(row.ticker):
            excluded += 1
            continue
        matched.append(row)

    cik_counts: dict[int, int] = {}
    for row in matched:
        cik_counts[row.cik] = cik_counts.get(row.cik, 0) + 1
    multi_class = sum(1 for n in cik_counts.values() if n > 1)
    return matched, excluded, multi_class


# ---------------------------------------------------------------------------
# Statement builders (compiled-SQL-tested)
# ---------------------------------------------------------------------------


def build_universe_upsert(
    rows: list[SecTickerRow], synced_at: dt.datetime
) -> PgInsert:
    """INSERT ... ON CONFLICT (ticker) DO UPDATE for universe_constituents.

    New rows enter with status='active'.  On conflict, `status` is
    deliberately NOT overwritten: the backfill's 'no_tiingo_data' marks (and
    manual 'excluded' marks) must survive re-syncs, otherwise every sync
    would re-queue known-dead tickers for the backfill.
    """
    if not rows:
        raise ValueError("build_universe_upsert requires at least one row")
    values = [
        {
            "ticker": row.ticker,
            "cik": row.cik,
            "name": row.title,
            "status": "active",
            "source": UNIVERSE_SOURCE,
            "synced_at": synced_at,
        }
        for row in rows
    ]
    stmt = pg_insert(UniverseConstituent).values(values)
    return stmt.on_conflict_do_update(
        index_elements=[UniverseConstituent.ticker],
        set_={
            "cik": stmt.excluded.cik,
            "name": stmt.excluded.name,
            "source": stmt.excluded.source,
            "synced_at": stmt.excluded.synced_at,
        },
    )


# All mutable fundamentals columns — everything except the ticker PK.
_FUNDAMENTALS_COLUMNS = (
    "cik",
    "period_end",
    "book_equity",
    "total_assets",
    "net_income_ttm",
    "revenue",
    "gross_profit",
    "shares_outstanding",
    "quality_roa",
    "investment_growth",
    "profitability_gross",
    "source_filing_date",
    "synced_at",
)


def build_fundamentals_upsert(records: list[dict[str, Any]]) -> PgInsert:
    """INSERT ... ON CONFLICT (ticker) DO UPDATE for fundamentals_snapshot.

    *records* must contain 'ticker' plus all _FUNDAMENTALS_COLUMNS keys.
    Idempotent: re-running with the same rows never duplicates; conflicting
    rows get every fundamentals field overwritten with fresh values.
    """
    if not records:
        raise ValueError("build_fundamentals_upsert requires at least one record")
    stmt = pg_insert(FundamentalsSnapshot).values(records)
    return stmt.on_conflict_do_update(
        index_elements=[FundamentalsSnapshot.ticker],
        set_={col: getattr(stmt.excluded, col) for col in _FUNDAMENTALS_COLUMNS},
    )


# ---------------------------------------------------------------------------
# External I/O (injectable in tests)
# ---------------------------------------------------------------------------


async def download_sec_company_tickers() -> dict[str, Any]:
    """Download the official SEC crosswalk (fail loud on any HTTP error)."""
    async with httpx.AsyncClient(
        timeout=60.0,
        headers={"User-Agent": SEC_USER_AGENT},
        follow_redirects=True,
    ) as http:
        response = await http.get(SEC_TICKERS_URL)
        response.raise_for_status()
        data = response.json()
    if not isinstance(data, dict):
        raise ValueError(
            f"Unexpected SEC company_tickers.json shape: {type(data).__name__}"
        )
    return data


def mother_db_dsn() -> str:
    """The mother-DB DSN for asyncpg.

    Strips any SQLAlchemy driver qualifier ('postgresql+asyncpg://',
    'postgresql+psycopg://', ...) down to the plain 'postgresql://' scheme
    asyncpg requires.  NEVER log or print the returned value.
    """
    settings = get_settings()
    dsn = settings.investintell_db_url
    if not dsn:
        raise RuntimeError(
            "INVESTINTELL_DB_URL is not configured — cannot reach the mother DB."
        )
    return re.sub(r"^postgresql\+[a-z0-9_]+://", "postgresql://", dsn, count=1)


async def connect_mother_db() -> asyncpg.Connection:
    """Open a read-only asyncpg connection to the mother DB (one per sync run)."""
    return await asyncpg.connect(
        mother_db_dsn(),
        server_settings={"default_transaction_read_only": "on"},
    )


def save_sec_snapshot(raw: dict[str, Any], seeds_dir: Path, today: dt.date) -> Path:
    """Persist the dated SEC crosswalk snapshot under backend/seeds/ (versioned)."""
    seeds_dir.mkdir(parents=True, exist_ok=True)
    path = seeds_dir / f"sec_company_tickers_{today.strftime('%Y%m%d')}.json"
    path.write_text(json.dumps(raw, separators=(",", ":")) + "\n", encoding="utf-8")
    return path


# ---------------------------------------------------------------------------
# Orchestrator
# ---------------------------------------------------------------------------

_DEFAULT_SEEDS_DIR = Path(__file__).resolve().parents[2] / "seeds"


async def run_sync(
    *,
    dry_run: bool = False,
    download: Callable[[], Awaitable[dict[str, Any]]] = download_sec_company_tickers,
    connect_mother: Callable[[], Awaitable[asyncpg.Connection]] = connect_mother_db,
    session_factory: async_sessionmaker[AsyncSession] | None = None,
    seeds_dir: Path = _DEFAULT_SEEDS_DIR,
) -> SyncReport:
    """One full sync run.  See module docstring for the pipeline.

    With dry_run=True nothing is written: no seeds snapshot, no local DB
    session is even opened — only the counts are computed and returned.

    The keyword-injectable callables exist for tests (no live network/DB);
    production callers use the defaults.
    """
    report = SyncReport(dry_run=dry_run)
    now = dt.datetime.now(dt.UTC)

    # Step 1 — SEC crosswalk.
    raw = await download()
    sec_rows = parse_sec_company_tickers(raw)
    report.sec_rows = len(sec_rows)
    logger.info("SEC crosswalk: %d ticker rows parsed", report.sec_rows)
    if not dry_run:
        snapshot_path = save_sec_snapshot(raw, seeds_dir, now.date())
        logger.info("SEC snapshot saved: %s", snapshot_path)

    # Step 2 — mother DB active CIKs + fundamentals (read-only, one connection
    # for the whole run, always closed).
    conn = await connect_mother()
    try:
        active_records = await conn.fetch(ACTIVE_CIKS_SQL)
        active_ciks = {int(r["cik"]) for r in active_records}
        report.active_ciks = len(active_ciks)
        logger.info("Mother DB: %d active CIKs (period_end within 12 months)",
                    report.active_ciks)

        # Step 3 — universe selection.
        universe, excluded, multi_class = select_universe(sec_rows, active_ciks)
        report.matched_tickers = len(universe)
        report.sec_excluded_invalid = excluded
        report.multi_class_ciks = multi_class
        logger.info(
            "Universe: %d tickers matched by CIK (%d excluded for invalid "
            "characters; %d CIKs list multiple share classes)",
            report.matched_tickers, excluded, multi_class,
        )

        # Step 4 — latest fundamentals per universe CIK.
        universe_ciks = sorted({row.cik for row in universe})
        fundamentals_records = await conn.fetch(FUNDAMENTALS_SQL, universe_ciks)
    finally:
        await conn.close()

    fundamentals_by_cik = {int(r["cik"]): dict(r) for r in fundamentals_records}
    report.fundamentals_rows = len(fundamentals_by_cik)
    report.fundamentals_missing_ciks = len(
        set(universe_ciks) - set(fundamentals_by_cik)
    )
    logger.info(
        "Fundamentals: %d latest rows fetched (%d universe CIKs without a row)",
        report.fundamentals_rows, report.fundamentals_missing_ciks,
    )

    snapshot_values: list[dict[str, Any]] = []
    for row in universe:
        fund = fundamentals_by_cik.get(row.cik)
        if fund is None:
            # Active CIK without a fundamentals row should be impossible (the
            # active set is derived from the same table) — keep the
            # constituent, skip the snapshot, count it loudly above.
            continue
        snapshot_values.append(
            {"ticker": row.ticker, "synced_at": now}
            | {col: fund[col] for col in _FUNDAMENTALS_COLUMNS[:-1]}
        )

    if dry_run:
        logger.info("Dry run — skipping all local writes")
        return report

    # Step 4b — idempotent local upserts (parents first: FK ordering), one
    # transaction for the whole sync so a failed run never leaves a
    # half-updated universe.
    if session_factory is None:
        from app.core.db import AsyncSessionLocal

        session_factory = AsyncSessionLocal
    async with session_factory() as session:
        try:
            for chunk in chunked(universe, _UPSERT_CHUNK):
                await session.execute(build_universe_upsert(chunk, now))
                report.universe_upserted += len(chunk)
            for chunk_vals in chunked(snapshot_values, _UPSERT_CHUNK):
                await session.execute(build_fundamentals_upsert(chunk_vals))
                report.fundamentals_upserted += len(chunk_vals)
            await session.commit()
        except Exception:
            await session.rollback()
            raise

    logger.info(
        "Upserted %d universe_constituents and %d fundamentals_snapshot rows",
        report.universe_upserted, report.fundamentals_upserted,
    )
    return report
