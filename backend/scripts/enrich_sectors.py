"""Enrich universe_constituents.sector from the data-lake GICS maps.

Run from backend/:
    uv run python scripts/enrich_sectors.py            # real run (writes)
    uv run python scripts/enrich_sectors.py --dry-run  # counts only

Sources (data lake), per ticker, CUSIP map first then the ISIN→GICS map:
  - sec_cusip_ticker_map.gics_sector  — SEC CUSIP→ticker→GICS (US-centric core).
  - sec_isin_sector.gics_sector       — ISIN→GICS enrichment (OpenFIGI/YFinance),
                                        keyed by ticker; fills tickers the CUSIP
                                        map misses.
mode() picks the most common sector when a ticker maps to several rows;
COALESCE prefers the SEC CUSIP sector and falls back to the ISIN map.

Requires DATALAKE_DB_URL (read-only data-lake) and the app DB.
"""

import argparse
import asyncio
import logging
import pathlib
import sys

_BACKEND_ROOT = pathlib.Path(__file__).parent.parent
if str(_BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(_BACKEND_ROOT))

from sqlalchemy import text  # noqa: E402

from app.core.datalake import get_datalake_session  # noqa: E402
from app.core.db import AsyncSessionLocal  # noqa: E402

logger = logging.getLogger("enrich_sectors")

# Per ticker: the SEC CUSIP GICS sector, falling back to the ISIN→GICS map.
SECTOR_MAP_SQL = text("""
    WITH cusip AS (
        SELECT ticker, mode() WITHIN GROUP (ORDER BY gics_sector) AS sector
        FROM sec_cusip_ticker_map
        WHERE ticker IS NOT NULL AND gics_sector IS NOT NULL
        GROUP BY ticker
    ),
    isin AS (
        SELECT ticker, mode() WITHIN GROUP (ORDER BY gics_sector) AS sector
        FROM sec_isin_sector
        WHERE ticker IS NOT NULL AND gics_sector IS NOT NULL
        GROUP BY ticker
    )
    SELECT t.ticker, COALESCE(c.sector, i.sector) AS sector
    FROM (SELECT ticker FROM cusip UNION SELECT ticker FROM isin) t
    LEFT JOIN cusip c USING (ticker)
    LEFT JOIN isin i USING (ticker)
""")

UPDATE_SQL = text("""
    UPDATE universe_constituents AS u
    SET sector = :sector
    WHERE u.ticker = :ticker AND (u.sector IS DISTINCT FROM :sector)
""")

COVERAGE_SQL = text("""
    SELECT count(*) AS total, count(sector) AS with_sector
    FROM universe_constituents WHERE status = 'active'
""")


async def run(dry_run: bool) -> None:
    async for datalake in get_datalake_session():
        rows = (await datalake.execute(SECTOR_MAP_SQL)).all()
    logger.info("GICS maps (cusip+isin): %d tickers com setor", len(rows))
    if dry_run:
        return
    params = [{"ticker": ticker, "sector": sector} for ticker, sector in rows]
    async with AsyncSessionLocal() as session:
        if params:
            # Single set-based executemany instead of one round-trip per ticker.
            await session.execute(UPDATE_SQL, params)
        await session.commit()
        total, with_sector = (await session.execute(COVERAGE_SQL)).one()
    logger.info("cobertura: %d/%d constituintes ativos com setor", with_sector, total)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    asyncio.run(run(dry_run=args.dry_run))


if __name__ == "__main__":
    main()
