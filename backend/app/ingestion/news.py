"""On-demand-with-cache news ingestion (per ticker).

Same DB-first contract as the EOD service: routes never call Tiingo for news
directly — they call ``ensure_news``, which refreshes the ``news_items`` cache
through ``TiingoClient.get_news`` when stale, then read from the table.

Staleness model (deliberate, no schema change): freshness is derived from
``max(fetched_at)`` over the news rows containing the ticker.  Tradeoff: a
ticker with genuinely ZERO news has no rows, so ``max(fetched_at)`` is NULL
and every request re-fetches from Tiingo.  Accepted for now — the damage is
capped by the shared token-bucket rate limiter; a per-ticker "last news
check" column can fix this later if it ever matters.

Upsert semantics: ``ON CONFLICT (id) DO UPDATE`` overwrites all article
fields including ``tickers`` — Tiingo returns the FULL tickers list per item,
so overwrite (not merge) is correct.  ``fetched_at`` is bumped to now() on
conflict so refreshes count toward freshness.
"""

import datetime as dt

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import Insert as PgInsert
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.models.news_item import NewsItem
from app.tiingo.client import TiingoClient
from app.tiingo.models import TiingoNewsItem

# All mutable article columns of news_items — everything except the id PK
# and fetched_at (which is set to now() explicitly on conflict).
_NEWS_COLUMNS = ("title", "url", "source", "description", "published_at", "tickers")


def build_news_upsert(items: list[TiingoNewsItem]) -> PgInsert:
    """Bulk INSERT ... ON CONFLICT (id) DO UPDATE for news_items.

    Idempotent: re-running with the same articles never duplicates; conflicting
    rows get all article fields overwritten and ``fetched_at`` bumped to now().
    Ticker symbols are normalized to uppercase (Tiingo returns lowercase) so
    containment lookups match the route's uppercased symbol.
    """
    if not items:
        raise ValueError("build_news_upsert requires at least one item")
    values = [
        {
            "id": item.id,
            "title": item.title,
            "url": item.url,
            "source": item.source,
            "description": item.description,
            "published_at": item.published_date,
            "tickers": sorted({t.strip().upper() for t in item.tickers if t.strip()}),
        }
        for item in items
    ]
    stmt = pg_insert(NewsItem).values(values)
    return stmt.on_conflict_do_update(
        index_elements=[NewsItem.id],
        set_={col: getattr(stmt.excluded, col) for col in _NEWS_COLUMNS}
        | {"fetched_at": func.now()},
    )


async def ensure_news(
    session: AsyncSession,
    client: TiingoClient,
    ticker: str,
    limit: int = 50,
    *,
    staleness_minutes: float | None = None,
) -> int:
    """Guarantee the news cache for *ticker* is fresh; return rows upserted.

    Fresh (max(fetched_at) within ``news_staleness_minutes``): no Tiingo call,
    returns 0.  Stale or unknown: fetch up to *limit* articles and upsert.
    Tiingo errors propagate (fail loud — the route decides whether cached
    rows allow a degraded-but-declared response).
    """
    if staleness_minutes is None:
        staleness_minutes = get_settings().news_staleness_minutes

    symbol = ticker.strip().upper()
    last_fetched = await session.scalar(
        select(func.max(NewsItem.fetched_at)).where(NewsItem.tickers.contains([symbol]))
    )
    now = dt.datetime.now(dt.UTC)
    if last_fetched is not None and now - last_fetched <= dt.timedelta(
        minutes=staleness_minutes
    ):
        return 0

    items = await client.get_news([symbol], limit=limit)
    if not items:
        return 0

    try:
        await session.execute(build_news_upsert(items))
        await session.commit()
    except Exception:
        await session.rollback()
        raise
    return len(items)
