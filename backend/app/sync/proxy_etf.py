"""Daily EOD refresh for curated proxy/benchmark ETFs outside the stock universe.

``universe_constituents`` holds SEC-CIK *equities*; sector and thematic proxy
ETFs (the Select Sector SPDRs plus a few thematic sleeves) are not in it, so the
universe warmer (``run_backfill``) never touches them and they would otherwise
only be refreshed opportunistically by the request path. This job keeps a
curated proxy list fresh in ``eod_prices`` using the SAME incremental per-ticker
ingest as the request path / universe warmer (``ingest_one_ticker`` via
``process_ticker_list``): incremental from the in-DB watermark, full history for
a brand-new ticker, freshness-skip when already fetched within the window.

The ``cagg_eod_daily`` continuous aggregate is NOT refreshed here — it carries
its own TimescaleDB refresh policy (daily), so it re-materialises from
``eod_prices`` automatically once new rows land.

Run via scripts/refresh_proxy_etf_eod.py — never from any request path.
"""

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.sync.backfill import BackfillReport, process_ticker_list
from app.tiingo.client import TiingoClient

# Curated proxies for the macro-factor / sector-rotation work. Sector SPDRs
# (energy → discretionary) plus thematic/sector sleeves. Extend here as new
# proxies are added; the job is list-driven, not universe-driven.
PROXY_ETF_TICKERS: tuple[str, ...] = (
    "XLE", "XLV", "XLF", "XLI", "XLB", "XLP", "XLU", "XLC", "XLY",
    "GUNR", "IFRA", "IBB", "ICLN", "EQL", "PFF",
)


def _dedupe_upper(source: list[str] | tuple[str, ...]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for raw in source:
        ticker = raw.strip().upper()
        if ticker and ticker not in seen:
            seen.add(ticker)
            out.append(ticker)
    return out


async def run_proxy_etf_backfill(
    session: AsyncSession,
    client: TiingoClient,
    *,
    tickers: list[str] | None = None,
    staleness_hours: float | None = None,
) -> BackfillReport:
    """Refresh EOD prices for the curated proxy-ETF list.

    Args:
        session: Async DB session (per-ticker commit lives in ingest_one_ticker).
        client: Shared TiingoClient (rate limiter governs every request).
        tickers: Optional explicit subset (testing); defaults to
            ``PROXY_ETF_TICKERS``. Normalised to uppercase and de-duplicated.
        staleness_hours: Freshness window override; defaults to settings, so a
            re-run within the window is cheap and idempotent.
    """
    if staleness_hours is None:
        staleness_hours = get_settings().eod_staleness_hours
    todo = _dedupe_upper(list(tickers) if tickers else list(PROXY_ETF_TICKERS))
    return await process_ticker_list(
        session, client, todo, staleness_hours=staleness_hours
    )
