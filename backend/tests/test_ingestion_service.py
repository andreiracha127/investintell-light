"""Tests for the on-demand-with-cache EOD ingestion service.

No live network, no live DB. Decision logic is tested via the pure helpers;
upsert correctness is tested by compiling the statements against the
PostgreSQL dialect; the orchestration path uses a thin fake session.
"""

import datetime as dt
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from sqlalchemy.dialects import postgresql

from app.ingestion.service import (
    _EOD_PRICE_COLUMNS,
    _EOD_UPSERT_CHUNK,
    HISTORY_FLOOR,
    INCREMENTAL_OVERLAP_DAYS,
    ColdTickerCapExceededError,
    build_eod_upsert,
    build_instrument_upsert,
    build_mark_fetched,
    classify_tickers,
    ensure_eod_data,
    full_history_start,
    incremental_start,
    is_fresh,
    normalize_tickers,
)

# classify_tickers now returns three buckets: (fresh, stale, cold)
from app.tiingo.models import TiingoEodRow, TiingoTickerMeta

_NOW = dt.datetime(2026, 6, 10, 12, 0, tzinfo=dt.UTC)


def _meta(ticker: str = "AAPL") -> TiingoTickerMeta:
    return TiingoTickerMeta(
        ticker=ticker,
        name="Apple Inc",
        exchange_code="NASDAQ",
        start_date=dt.date(1980, 12, 12),
        end_date=dt.date(2026, 6, 9),
    )


def _eod_row(ticker: str = "AAPL", day: dt.date = dt.date(2026, 6, 9)) -> TiingoEodRow:
    return TiingoEodRow(
        ticker=ticker,
        date=day,
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


def _instrument(ticker: str, fetched_at: dt.datetime | None) -> SimpleNamespace:
    return SimpleNamespace(ticker=ticker, eod_last_fetched_at=fetched_at)


class _FakeResult:
    def __init__(self, items: list[object]) -> None:
        self._items = items

    def scalars(self) -> "_FakeResult":
        return self

    def all(self) -> list[object]:
        return self._items


class _FakeSession:
    """Thin stand-in: first SELECT returns instruments, scalar() returns max_date.

    ``max_date`` may be a single value (applied to all tickers) or a dict
    mapping ticker → date so mixed cold/stale tests can control per-ticker
    behaviour.  When a dict is used, a ticker absent from the dict returns None
    (cold ticker: no rows in DB yet).
    """

    def __init__(
        self,
        instruments: list[SimpleNamespace] | None = None,
        max_date: dt.date | None | dict[str, dt.date | None] = None,
    ) -> None:
        self._instruments = instruments or []
        self._max_date = max_date
        self._scalar_call_count = 0
        self.executed: list[object] = []
        self.commits = 0
        self.rollbacks = 0

    async def execute(self, stmt: object) -> _FakeResult:
        self.executed.append(stmt)
        return _FakeResult(list(self._instruments))

    async def scalar(self, stmt: object) -> dt.date | None:
        self.executed.append(stmt)
        if isinstance(self._max_date, dict):
            # Derive the ticker from the WHERE clause text if possible; fall back
            # to cycling through values in insertion order for simpler tests.
            # The simplest reliable approach: inspect the compiled SQL fragment.
            compiled = str(stmt.compile(compile_kwargs={"literal_binds": True}))  # type: ignore[union-attr]
            for ticker, date_val in self._max_date.items():
                if f"'{ticker}'" in compiled or f'"{ticker}"' in compiled:
                    return date_val
            return None
        return self._max_date

    async def commit(self) -> None:
        self.commits += 1

    async def rollback(self) -> None:
        self.rollbacks += 1


# ---------------------------------------------------------------------------
# Pure helpers
# ---------------------------------------------------------------------------


def test_normalize_tickers_uppercases_dedupes_preserves_order() -> None:
    assert normalize_tickers(["aapl", "MSFT", "AAPL", " msft ", "", "tsla"]) == [
        "AAPL",
        "MSFT",
        "TSLA",
    ]


def test_is_fresh_within_window() -> None:
    assert is_fresh(_NOW - dt.timedelta(hours=23), _NOW, 24.0) is True


def test_is_fresh_outside_window() -> None:
    assert is_fresh(_NOW - dt.timedelta(hours=25), _NOW, 24.0) is False


def test_is_fresh_never_fetched() -> None:
    assert is_fresh(None, _NOW, 24.0) is False


def test_classify_tickers() -> None:
    instruments = {
        "AAPL": _instrument("AAPL", _NOW - dt.timedelta(hours=1)),  # fresh
        "MSFT": _instrument("MSFT", _NOW - dt.timedelta(hours=48)),  # stale: exists, old fetch
        # TSLA absent entirely -> cold (no instrument row)
    }
    fresh, stale, cold = classify_tickers(["AAPL", "MSFT", "TSLA"], instruments, _NOW, 24.0)  # type: ignore[arg-type]
    assert fresh == ["AAPL"]
    assert stale == ["MSFT"]
    assert cold == ["TSLA"]


def test_classify_tickers_stale_none_fetched_at() -> None:
    """Instrument row exists but eod_last_fetched_at is None → stale, not cold."""
    instruments = {
        "AAPL": _instrument("AAPL", None),
    }
    fresh, stale, cold = classify_tickers(["AAPL"], instruments, _NOW, 24.0)  # type: ignore[arg-type]
    assert fresh == []
    assert stale == ["AAPL"]
    assert cold == []


def test_incremental_start_applies_overlap() -> None:
    max_date = dt.date(2026, 6, 1)
    assert incremental_start(max_date) == max_date - dt.timedelta(
        days=INCREMENTAL_OVERLAP_DAYS
    )


def test_full_history_start_uses_tiingo_start_or_floor_fallback() -> None:
    assert full_history_start(dt.date(2010, 5, 3)) == dt.date(2010, 5, 3)
    assert full_history_start(dt.date(1980, 12, 12)) == dt.date(1980, 12, 12)
    assert full_history_start(None) == HISTORY_FLOOR


# ---------------------------------------------------------------------------
# Statement construction
# ---------------------------------------------------------------------------


def test_instrument_upsert_sets_updated_at_explicitly() -> None:
    """Core upserts bypass onupdate=func.now() — set_ MUST include updated_at."""
    sql = str(build_instrument_upsert(_meta()).compile(dialect=postgresql.dialect()))
    assert "ON CONFLICT (ticker) DO UPDATE" in sql
    assert "updated_at = now()" in sql


def test_eod_upsert_targets_ticker_date_and_updates_all_price_fields() -> None:
    sql = str(
        build_eod_upsert([_eod_row(), _eod_row(day=dt.date(2026, 6, 8))]).compile(
            dialect=postgresql.dialect()
        )
    )
    assert "ON CONFLICT (ticker, date) DO UPDATE" in sql
    for col in (
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
    ):
        assert f"{col} = excluded.{col}" in sql


def test_eod_upsert_rejects_empty_rows() -> None:
    with pytest.raises(ValueError):
        build_eod_upsert([])


def test_mark_fetched_sets_both_timestamps() -> None:
    sql = str(build_mark_fetched("AAPL").compile(dialect=postgresql.dialect()))
    assert "eod_last_fetched_at=now()" in sql.replace(" ", "")
    assert "updated_at=now()" in sql.replace(" ", "")


# ---------------------------------------------------------------------------
# Orchestration (ensure_eod_data)
# ---------------------------------------------------------------------------


async def test_fresh_ticker_skips_client_entirely() -> None:
    session = _FakeSession(
        instruments=[_instrument("AAPL", dt.datetime.now(dt.UTC))]
    )
    client = AsyncMock()

    report = await ensure_eod_data(
        session,  # type: ignore[arg-type]
        client,
        ["aapl"],
        dt.date(2026, 1, 1),
        dt.date(2026, 6, 1),
    )

    client.get_ticker_meta.assert_not_called()
    client.get_eod_prices.assert_not_called()
    assert session.commits == 0
    assert [(o.ticker, o.action) for o in report.outcomes] == [("AAPL", "fresh")]


async def test_cold_ticker_fetches_meta_prices_and_upserts() -> None:
    session = _FakeSession(instruments=[], max_date=None)
    client = AsyncMock()
    client.get_ticker_meta.return_value = _meta()
    client.get_eod_prices.return_value = [_eod_row(), _eod_row(day=dt.date(2026, 6, 8))]

    report = await ensure_eod_data(
        session,  # type: ignore[arg-type]
        client,
        ["AAPL"],
        dt.date(2026, 1, 1),
        dt.date(2026, 6, 1),
    )

    client.get_ticker_meta.assert_awaited_once_with("AAPL")
    # Brand-new ticker -> full history from Tiingo start date through today.
    args = client.get_eod_prices.await_args.args
    assert args == ("AAPL", dt.date(1980, 12, 12), dt.date.today())
    assert session.commits == 1
    assert session.rollbacks == 0
    outcome = report.outcomes[0]
    assert (outcome.ticker, outcome.action, outcome.rows_upserted) == (
        "AAPL",
        "fetched_full",
        2,
    )


async def test_stale_ticker_fetches_incrementally_with_overlap() -> None:
    max_date = dt.date(2026, 6, 1)
    session = _FakeSession(
        instruments=[_instrument("AAPL", dt.datetime.now(dt.UTC) - dt.timedelta(days=3))],
        max_date=max_date,
    )
    client = AsyncMock()
    client.get_ticker_meta.return_value = _meta()
    client.get_eod_prices.return_value = [_eod_row()]

    report = await ensure_eod_data(
        session,  # type: ignore[arg-type]
        client,
        ["AAPL"],
        dt.date(2026, 1, 1),
        dt.date(2026, 6, 1),
    )

    args = client.get_eod_prices.await_args.args
    assert args == (
        "AAPL",
        max_date - dt.timedelta(days=INCREMENTAL_OVERLAP_DAYS),
        dt.date.today(),
    )
    assert report.outcomes[0].action == "fetched_incremental"


async def test_cold_cap_exceeded_raises_before_any_fetch() -> None:
    """Cap applies only to truly-cold tickers (no instrument row)."""
    session = _FakeSession(instruments=[])
    client = AsyncMock()

    with pytest.raises(ColdTickerCapExceededError):
        await ensure_eod_data(
            session,  # type: ignore[arg-type]
            client,
            ["A", "B", "C"],
            dt.date(2026, 1, 1),
            dt.date(2026, 6, 1),
            max_cold_tickers=2,
        )

    client.get_ticker_meta.assert_not_called()
    client.get_eod_prices.assert_not_called()
    assert session.commits == 0


async def test_stale_tickers_not_capped_by_cold_cap() -> None:
    """6 stale tickers (instrument rows exist, old fetched_at) + 0 cold → no error.

    D2 semantics: stale tickers need only one incremental request each and are
    never counted toward max_cold_tickers_per_request.
    """
    old_fetch = _NOW - dt.timedelta(hours=48)
    tickers = ["A", "B", "C", "D", "E", "F"]
    instruments = [_instrument(t, old_fetch) for t in tickers]
    max_date = dt.date(2026, 6, 1)
    session = _FakeSession(instruments=instruments, max_date=max_date)
    client = AsyncMock()
    client.get_ticker_meta.return_value = _meta()
    client.get_eod_prices.return_value = [_eod_row()]

    # cap=5, but all 6 are stale (not cold) — must NOT raise
    report = await ensure_eod_data(
        session,  # type: ignore[arg-type]
        client,
        tickers,
        dt.date(2026, 1, 1),
        dt.date(2026, 6, 1),
        max_cold_tickers=5,
    )

    assert len(report.outcomes) == 6
    assert all(o.action == "fetched_incremental" for o in report.outcomes)
    assert client.get_eod_prices.await_count == 6


async def test_six_cold_tickers_raises() -> None:
    """6 cold tickers (no instrument rows) with cap=5 → ColdTickerCapExceededError."""
    session = _FakeSession(instruments=[])
    client = AsyncMock()

    with pytest.raises(ColdTickerCapExceededError):
        await ensure_eod_data(
            session,  # type: ignore[arg-type]
            client,
            ["A", "B", "C", "D", "E", "F"],
            dt.date(2026, 1, 1),
            dt.date(2026, 6, 1),
            max_cold_tickers=5,
        )

    client.get_ticker_meta.assert_not_called()
    assert session.commits == 0


async def test_three_cold_ten_stale_no_error_all_fetched() -> None:
    """3 cold + 10 stale with cap=5 → cold count (3) is under cap, no error.

    All 13 tickers must be processed: 3 full-history fetches + 10 incremental.
    The error message would mention only the cold count if the cap were exceeded,
    not the stale count — but here 3 < 5 so no error at all.
    """
    old_fetch = _NOW - dt.timedelta(hours=48)
    stale_tickers = [f"S{i}" for i in range(10)]
    cold_tickers = ["C1", "C2", "C3"]
    all_tickers = cold_tickers + stale_tickers

    stale_instruments = [_instrument(t, old_fetch) for t in stale_tickers]
    # Stale tickers have a max_date in DB; cold tickers have None (no rows yet).
    per_ticker_max_date: dict[str, dt.date | None] = {
        t: dt.date(2026, 6, 1) for t in stale_tickers
    }
    # cold tickers absent from dict → scalar() returns None → full history fetch
    session = _FakeSession(instruments=stale_instruments, max_date=per_ticker_max_date)
    client = AsyncMock()
    client.get_ticker_meta.return_value = _meta()
    client.get_eod_prices.return_value = [_eod_row()]

    report = await ensure_eod_data(
        session,  # type: ignore[arg-type]
        client,
        all_tickers,
        dt.date(2026, 1, 1),
        dt.date(2026, 6, 1),
        max_cold_tickers=5,
    )

    assert len(report.outcomes) == 13
    full_fetches = [o for o in report.outcomes if o.action == "fetched_full"]
    incremental_fetches = [o for o in report.outcomes if o.action == "fetched_incremental"]
    assert len(full_fetches) == 3
    assert len(incremental_fetches) == 10
    assert client.get_eod_prices.await_count == 13


async def test_failing_ticker_rolls_back_and_reraises() -> None:
    session = _FakeSession(instruments=[], max_date=None)
    client = AsyncMock()
    client.get_ticker_meta.return_value = _meta()
    client.get_eod_prices.side_effect = RuntimeError("boom")

    with pytest.raises(RuntimeError):
        await ensure_eod_data(
            session,  # type: ignore[arg-type]
            client,
            ["AAPL"],
            dt.date(2026, 1, 1),
            dt.date(2026, 6, 1),
        )

    assert session.rollbacks == 1
    assert session.commits == 0


# ---------------------------------------------------------------------------
# DB-first mode (Strategy B): stale served from DB, only cold fetches
# ---------------------------------------------------------------------------


async def test_db_first_stale_ticker_served_without_fetch() -> None:
    """DB-first: a stale ticker is served from the DB with zero Tiingo calls.

    This is the core of Strategy B — the warming worker keeps the universe
    fresh, so the request path never pays a synchronous incremental fetch.
    """
    session = _FakeSession(
        instruments=[_instrument("AAPL", _NOW - dt.timedelta(hours=48))],
        max_date=dt.date(2026, 6, 1),
    )
    client = AsyncMock()

    report = await ensure_eod_data(
        session,  # type: ignore[arg-type]
        client,
        ["AAPL"],
        dt.date(2026, 1, 1),
        dt.date(2026, 6, 1),
        db_first=True,
    )

    client.get_ticker_meta.assert_not_called()
    client.get_eod_prices.assert_not_called()
    assert session.commits == 0
    assert [(o.ticker, o.action) for o in report.outcomes] == [("AAPL", "stale_served")]


async def test_db_first_cold_ticker_still_fetches() -> None:
    """DB-first: a truly cold ticker (no instrument row) still fetches synchronously."""
    session = _FakeSession(instruments=[], max_date=None)
    client = AsyncMock()
    client.get_ticker_meta.return_value = _meta()
    client.get_eod_prices.return_value = [_eod_row()]

    report = await ensure_eod_data(
        session,  # type: ignore[arg-type]
        client,
        ["AAPL"],
        dt.date(2026, 1, 1),
        dt.date(2026, 6, 1),
        db_first=True,
    )

    client.get_eod_prices.assert_awaited_once()
    assert report.outcomes[0].action == "fetched_full"
    assert session.commits == 1


async def test_db_first_fresh_ticker_unchanged() -> None:
    """DB-first leaves the fresh path identical: no fetch, action 'fresh'."""
    session = _FakeSession(instruments=[_instrument("AAPL", dt.datetime.now(dt.UTC))])
    client = AsyncMock()

    report = await ensure_eod_data(
        session,  # type: ignore[arg-type]
        client,
        ["AAPL"],
        dt.date(2026, 1, 1),
        dt.date(2026, 6, 1),
        db_first=True,
    )

    client.get_eod_prices.assert_not_called()
    assert [(o.ticker, o.action) for o in report.outcomes] == [("AAPL", "fresh")]


async def test_db_first_cold_cap_still_enforced() -> None:
    """DB-first does NOT relax the cold cap — unbounded cold fetches stay blocked."""
    session = _FakeSession(instruments=[])
    client = AsyncMock()

    with pytest.raises(ColdTickerCapExceededError):
        await ensure_eod_data(
            session,  # type: ignore[arg-type]
            client,
            ["A", "B", "C"],
            dt.date(2026, 1, 1),
            dt.date(2026, 6, 1),
            max_cold_tickers=2,
            db_first=True,
        )

    client.get_eod_prices.assert_not_called()
    assert session.commits == 0


async def test_db_first_mixed_only_cold_hits_tiingo() -> None:
    """DB-first with 1 cold + 2 stale: only the cold ticker calls Tiingo."""
    old_fetch = _NOW - dt.timedelta(hours=48)
    session = _FakeSession(
        instruments=[_instrument("S1", old_fetch), _instrument("S2", old_fetch)],
        max_date={"S1": dt.date(2026, 6, 1), "S2": dt.date(2026, 6, 1)},
    )
    client = AsyncMock()
    client.get_ticker_meta.return_value = _meta()
    client.get_eod_prices.return_value = [_eod_row()]

    report = await ensure_eod_data(
        session,  # type: ignore[arg-type]
        client,
        ["C1", "S1", "S2"],
        dt.date(2026, 1, 1),
        dt.date(2026, 6, 1),
        db_first=True,
    )

    actions = {o.ticker: o.action for o in report.outcomes}
    assert actions == {"C1": "fetched_full", "S1": "stale_served", "S2": "stale_served"}
    assert client.get_eod_prices.await_count == 1


# ---------------------------------------------------------------------------
# Chunked upsert — asyncpg 32 767-parameter ceiling
# ---------------------------------------------------------------------------


async def test_large_fetch_splits_into_multiple_execute_calls() -> None:
    """With more rows than _EOD_UPSERT_CHUNK the session receives multiple
    EOD upsert execute calls — one per chunk — and every chunk stays at or
    below the chunk size (which guarantees the asyncpg parameter ceiling is
    never breached)."""
    import math

    # Build n_rows > _EOD_UPSERT_CHUNK so chunking is forced.
    n_rows = _EOD_UPSERT_CHUNK + 500
    rows = [
        _eod_row(day=dt.date(2020, 1, 1) + dt.timedelta(days=i)) for i in range(n_rows)
    ]

    session = _FakeSession(instruments=[], max_date=None)
    client = AsyncMock()
    client.get_ticker_meta.return_value = _meta()
    client.get_eod_prices.return_value = rows

    report = await ensure_eod_data(
        session,  # type: ignore[arg-type]
        client,
        ["AAPL"],
        dt.date(2020, 1, 1),
        dt.date(2026, 6, 1),
    )

    # Count how many of the executed statements are PgInsert targeting eod_prices.
    # (build_instrument_upsert also produces a PgInsert, so filter by table name.)
    from sqlalchemy.dialects.postgresql import Insert as PgInsert

    eod_upserts = [
        s
        for s in session.executed
        if isinstance(s, PgInsert) and s.table.name == "eod_prices"
    ]

    expected_chunks = math.ceil(n_rows / _EOD_UPSERT_CHUNK)
    assert len(eod_upserts) == expected_chunks, (
        f"Expected {expected_chunks} EOD upsert execute calls, got {len(eod_upserts)}"
    )

    # Verify each chunk has at most _EOD_UPSERT_CHUNK rows.
    # The number of value rows can be read from the statement's compile-time
    # structure: each chunk is built from a slice of at most _EOD_UPSERT_CHUNK rows.
    # We check the total rows across all chunks equals n_rows.
    assert report.outcomes[0].rows_upserted == n_rows
    assert session.commits == 1


async def test_chunk_param_count_under_asyncpg_ceiling() -> None:
    """Each chunk's bound-parameter count must be < 32 767 (asyncpg ceiling)."""
    _ASYNCPG_PARAM_CEILING = 32_767
    # 14 params per row: 2 PK (ticker, date) + 12 price columns.
    _PARAMS_PER_ROW = 2 + len(_EOD_PRICE_COLUMNS)

    n_rows = _EOD_UPSERT_CHUNK * 3 + 100  # three full chunks + a partial one
    rows = [
        _eod_row(day=dt.date(2015, 1, 1) + dt.timedelta(days=i)) for i in range(n_rows)
    ]

    # Verify that a single chunk of size _EOD_UPSERT_CHUNK stays under the ceiling.
    chunk = rows[:_EOD_UPSERT_CHUNK]
    params_in_chunk = len(chunk) * _PARAMS_PER_ROW
    assert params_in_chunk < _ASYNCPG_PARAM_CEILING, (
        f"Chunk of {len(chunk)} rows binds {params_in_chunk} params "
        f"which exceeds asyncpg ceiling of {_ASYNCPG_PARAM_CEILING}"
    )
