"""Enrich universe_constituents.sector from the data-lake sec_cusip_ticker_map.

Run from backend/:
    uv run python scripts/enrich_sectors.py            # real run (writes)
    uv run python scripts/enrich_sectors.py --dry-run  # counts only

Requires DATALAKE_DB_URL (read-only data-lake) and the local DB. The map has
~7.0k tickers with GICS sector (11 sectors); coverage over the ~5k-ticker
universe is reported at the end. mode() picks the most common sector when a
ticker maps to several CUSIPs.
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

SECTOR_MAP_SQL = text("""
    SELECT upper(ticker) AS ticker,
           mode() WITHIN GROUP (ORDER BY gics_sector) AS sector
    FROM sec_cusip_ticker_map
    WHERE ticker IS NOT NULL AND gics_sector IS NOT NULL
    GROUP BY upper(ticker)
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
    logger.info("sec_cusip_ticker_map: %d tickers com setor", len(rows))
    if dry_run:
        return
    async with AsyncSessionLocal() as session:
        for ticker, sector in rows:
            await session.execute(UPDATE_SQL, {"ticker": ticker, "sector": sector})
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
