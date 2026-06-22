"""Tests for the proxy-ETF EOD refresh (app/sync/proxy_etf.py).

No live network, no live DB: TiingoClient and AsyncSession are thin fakes.
Covers: the curated list is processed (incremental ingest), freshness skipping,
per-ticker failure tolerance with one retry, and explicit-subset override.
The proxy job is list-driven (no universe SELECT), so it reuses the shared
``process_ticker_list`` core that ``run_backfill`` also uses.
"""

import datetime as dt
from types import SimpleNamespace
from typing import Any

from app.sync.proxy_etf import PROXY_ETF_TICKERS, run_proxy_etf_backfill
from tests.test_universe_backfill import FakeClient


class _FakeResult:
    def __init__(self, items: list[Any]) -> None:
        self._items = items

    def scalars(self) -> "_FakeResult":
        return self

    def all(self) -> list[Any]:
        return self._items


class ProxyFakeSession:
    """AsyncSession stand-in for the list-driven proxy job (no initial SELECT).

    Every execute() is just recorded (upserts / status marks). get() consults
    the instruments dict for freshness; scalar() returns None for max(date)
    (cold → full history) until the final count(*).
    """

    def __init__(self, instruments: dict[str, SimpleNamespace] | None = None) -> None:
        self._instruments = instruments or {}
        self.executed: list[Any] = []
        self.commits = 0
        self.rollbacks = 0

    async def execute(self, stmt: Any) -> _FakeResult:
        self.executed.append(stmt)
        return _FakeResult([])

    async def get(self, model: Any, ticker: str) -> Any:
        return self._instruments.get(ticker)

    async def scalar(self, stmt: Any) -> Any:
        if "count" in str(stmt).lower():
            return 999
        return None  # max(date): every ticker is cold → full history

    async def commit(self) -> None:
        self.commits += 1

    async def rollback(self) -> None:
        self.rollbacks += 1


async def test_proxy_backfill_processes_full_curated_list() -> None:
    session = ProxyFakeSession()
    client = FakeClient({})
    report = await run_proxy_etf_backfill(session, client)  # type: ignore[arg-type]
    assert report.total_considered == len(PROXY_ETF_TICKERS)
    assert report.ingested_full == len(PROXY_ETF_TICKERS)
    assert report.errors == {}
    assert report.eod_price_rows_total == 999
    assert session.commits == len(PROXY_ETF_TICKERS)  # one commit per ticker
    # Each curated ticker reached Tiingo exactly once.
    assert set(client.meta_calls) == set(PROXY_ETF_TICKERS)


async def test_proxy_backfill_explicit_subset_overrides_and_dedupes() -> None:
    session = ProxyFakeSession()
    client = FakeClient({})
    report = await run_proxy_etf_backfill(
        session,  # type: ignore[arg-type]
        client,  # type: ignore[arg-type]
        tickers=["xle", " xlf ", "XLE"],  # mixed case + dup
        staleness_hours=24.0,
    )
    assert report.total_considered == 2
    assert client.meta_calls == ["XLE", "XLF"]


async def test_proxy_backfill_skips_fresh() -> None:
    fresh = SimpleNamespace(ticker="XLE", eod_last_fetched_at=dt.datetime.now(dt.UTC))
    session = ProxyFakeSession(instruments={"XLE": fresh})
    client = FakeClient({})
    report = await run_proxy_etf_backfill(
        session,  # type: ignore[arg-type]
        client,  # type: ignore[arg-type]
        tickers=["XLE", "XLF"],
        staleness_hours=24.0,
    )
    assert report.skipped_fresh == 1
    assert report.ingested_full == 1
    assert client.meta_calls == ["XLF"]  # no Tiingo call for the fresh ticker


async def test_proxy_backfill_per_ticker_failure_tolerated_with_retry() -> None:
    session = ProxyFakeSession()
    client = FakeClient({"XLF": "fail_always"})
    report = await run_proxy_etf_backfill(
        session,  # type: ignore[arg-type]
        client,  # type: ignore[arg-type]
        tickers=["XLE", "XLF", "XLV"],
    )
    assert report.ingested_full == 2
    assert "XLF" in report.errors
    # Initial attempt + exactly one end-of-run retry.
    assert client.meta_calls.count("XLF") == 2
