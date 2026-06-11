"""Tests for the universe EOD backfill (app/sync/backfill.py).

No live network, no live DB: TiingoClient and AsyncSession are thin fakes.
Covers: not-found marks status, per-ticker failure tolerance, the end-of-run
retry pass, freshness skipping, and the absence of the cold-ticker cap in
the batch path.
"""

import datetime as dt
from types import SimpleNamespace
from typing import Any

from sqlalchemy.dialects import postgresql

from app.sync.backfill import build_mark_no_tiingo_data, run_backfill
from app.tiingo.exceptions import TiingoNotFoundError, TiingoServerError
from app.tiingo.models import TiingoEodRow, TiingoTickerMeta

_NOW = dt.datetime(2026, 6, 11, 12, 0, tzinfo=dt.UTC)


def _meta(ticker: str) -> TiingoTickerMeta:
    return TiingoTickerMeta(
        ticker=ticker,
        name=f"{ticker} Inc",
        exchange_code="NYSE",
        start_date=dt.date(2020, 1, 2),
        end_date=dt.date(2026, 6, 10),
    )


def _eod_row(ticker: str) -> TiingoEodRow:
    return TiingoEodRow(
        ticker=ticker,
        date=dt.date(2026, 6, 10),
        open=1.0,
        high=2.0,
        low=0.5,
        close=1.5,
        volume=100,
        adj_open=1.0,
        adj_high=2.0,
        adj_low=0.5,
        adj_close=1.5,
        adj_volume=100,
        div_cash=0.0,
        split_factor=1.0,
    )


class FakeClient:
    """TiingoClient stand-in: per-ticker scripted behaviour.

    behaviours[ticker] may be:
      - "ok"          → meta + one EOD row
      - "not_found"   → TiingoNotFoundError on meta fetch
      - "fail_once"   → TiingoServerError on first meta fetch, ok afterwards
      - "fail_always" → TiingoServerError on every meta fetch
    """

    def __init__(self, behaviours: dict[str, str]) -> None:
        self._behaviours = behaviours
        self.meta_calls: list[str] = []

    async def get_ticker_meta(self, ticker: str) -> TiingoTickerMeta:
        self.meta_calls.append(ticker)
        behaviour = self._behaviours.get(ticker, "ok")
        if behaviour == "not_found":
            raise TiingoNotFoundError(f"{ticker} unknown")
        if behaviour == "fail_always":
            raise TiingoServerError(f"{ticker} 500")
        if behaviour == "fail_once" and self.meta_calls.count(ticker) == 1:
            raise TiingoServerError(f"{ticker} transient 500")
        return _meta(ticker)

    async def get_eod_prices(
        self, ticker: str, start: dt.date, end: dt.date
    ) -> list[TiingoEodRow]:
        return [_eod_row(ticker)]


class _FakeResult:
    def __init__(self, items: list[Any]) -> None:
        self._items = items

    def scalars(self) -> "_FakeResult":
        return self

    def all(self) -> list[Any]:
        return self._items


class FakeSession:
    """AsyncSession stand-in for the backfill loop.

    - First execute() of a SELECT returns the active-ticker list; every other
      execute (upserts, status marks) is recorded.
    - get(Instrument, ticker) consults the `instruments` dict (freshness).
    - scalar() answers max(date) (None → cold) then the final count(*).
    """

    def __init__(
        self,
        active_tickers: list[str],
        instruments: dict[str, SimpleNamespace] | None = None,
    ) -> None:
        self._active_tickers = active_tickers
        self._instruments = instruments or {}
        self.executed: list[Any] = []
        self.commits = 0
        self.rollbacks = 0
        self._select_served = False

    async def execute(self, stmt: Any) -> _FakeResult:
        self.executed.append(stmt)
        if not self._select_served:
            self._select_served = True
            return _FakeResult(list(self._active_tickers))
        return _FakeResult([])

    async def get(self, model: Any, ticker: str) -> Any:
        return self._instruments.get(ticker)

    async def scalar(self, stmt: Any) -> Any:
        compiled = str(stmt)
        if "count" in compiled.lower():
            return 12345
        return None  # max(date): every ticker is cold

    async def commit(self) -> None:
        self.commits += 1

    async def rollback(self) -> None:
        self.rollbacks += 1


# ---------------------------------------------------------------------------
# Status mark statement
# ---------------------------------------------------------------------------


def test_mark_no_tiingo_data_statement() -> None:
    sql = str(
        build_mark_no_tiingo_data("DEADCO").compile(
            dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True}
        )
    )
    assert "UPDATE universe_constituents" in sql
    assert "no_tiingo_data" in sql
    assert "'DEADCO'" in sql


# ---------------------------------------------------------------------------
# run_backfill behaviour
# ---------------------------------------------------------------------------


async def test_backfill_happy_path_ingests_all() -> None:
    session = FakeSession(["AAA", "BBB", "CCC"])
    client = FakeClient({})
    report = await run_backfill(session, client)  # type: ignore[arg-type]
    assert report.total_considered == 3
    assert report.ingested_full == 3
    assert report.errors == {}
    assert report.eod_price_rows_total == 12345
    assert session.commits == 3  # one commit per ticker


async def test_backfill_not_found_marks_status_and_continues() -> None:
    session = FakeSession(["AAA", "DEADCO", "CCC"])
    client = FakeClient({"DEADCO": "not_found"})
    report = await run_backfill(session, client)  # type: ignore[arg-type]
    assert report.not_found == 1
    assert report.ingested_full == 2  # batch was NOT aborted
    assert report.errors == {}
    # The status-mark UPDATE was executed and committed.
    def _pg_sql(stmt: Any) -> str:
        return str(stmt.compile(dialect=postgresql.dialect()))

    marked = [
        s
        for s in session.executed[1:]  # skip the constituents SELECT
        if "UPDATE universe_constituents" in _pg_sql(s)
    ]
    assert len(marked) == 1


async def test_backfill_per_ticker_failure_does_not_abort_batch() -> None:
    session = FakeSession(["AAA", "BOOM", "CCC"])
    client = FakeClient({"BOOM": "fail_always"})
    report = await run_backfill(session, client)  # type: ignore[arg-type]
    assert report.ingested_full == 2
    assert "BOOM" in report.errors
    assert "TiingoServerError" in report.errors["BOOM"]
    # Initial attempt + one end-of-run retry, no more.
    assert client.meta_calls.count("BOOM") == 2


async def test_backfill_transient_error_recovers_on_retry() -> None:
    session = FakeSession(["AAA", "FLAKY"])
    client = FakeClient({"FLAKY": "fail_once"})
    report = await run_backfill(session, client)  # type: ignore[arg-type]
    assert report.ingested_full == 2  # FLAKY recovered in the retry pass
    assert report.recovered_on_retry == 1
    assert report.errors == {}


async def test_backfill_skips_fresh_instruments() -> None:
    fresh = SimpleNamespace(
        ticker="AAA", eod_last_fetched_at=dt.datetime.now(dt.UTC)
    )
    session = FakeSession(["AAA", "BBB"], instruments={"AAA": fresh})
    client = FakeClient({})
    report = await run_backfill(
        session,  # type: ignore[arg-type]
        client,  # type: ignore[arg-type]
        staleness_hours=24.0,
    )
    assert report.skipped_fresh == 1
    assert report.ingested_full == 1
    assert client.meta_calls == ["BBB"]  # no Tiingo call for the fresh ticker


async def test_backfill_cold_cap_not_applied() -> None:
    """The batch path must ingest arbitrarily many cold tickers — the
    per-request cap (max_cold_tickers_per_request, default 5) does not apply."""
    many = [f"T{i:03d}" for i in range(25)]  # 25 cold tickers > cap of 5
    session = FakeSession(many)
    client = FakeClient({})
    report = await run_backfill(session, client)  # type: ignore[arg-type]
    assert report.ingested_full == 25
    assert report.errors == {}


async def test_backfill_select_filters() -> None:
    """--tickers and --limit shape the SELECT, not post-hoc filtering."""
    session = FakeSession(["AAA"])
    client = FakeClient({})
    await run_backfill(
        session,  # type: ignore[arg-type]
        client,  # type: ignore[arg-type]
        limit=10,
        tickers=["aaa", " bbb "],
    )
    select_sql = str(session.executed[0]).upper()
    assert "STATUS" in select_sql
    assert "LIMIT" in select_sql
    assert "IN (" in select_sql
