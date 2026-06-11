"""Tests for the mother-DB universe sync (app/sync/mother_db.py).

No live network, no live DB: the SEC download and the mother-DB connection
are injected fakes; local upserts are checked by compiling the statements
against the PostgreSQL dialect; run_sync is exercised end-to-end with fakes.
"""

import datetime as dt
import json
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy.dialects import postgresql

from app.sync.mother_db import (
    SecTickerRow,
    build_fundamentals_upsert,
    build_universe_upsert,
    is_valid_universe_ticker,
    mother_db_dsn,
    parse_sec_company_tickers,
    run_sync,
    select_universe,
)

_NOW = dt.datetime(2026, 6, 11, 12, 0, tzinfo=dt.UTC)

# ---------------------------------------------------------------------------
# Fixtures / fakes
# ---------------------------------------------------------------------------

# Shape of the real SEC file: dict keyed by stringified index.
SEC_RAW = {
    "0": {"cik_str": 320193, "ticker": "AAPL", "title": "Apple Inc."},
    "1": {"cik_str": 1652044, "ticker": "GOOGL", "title": "Alphabet Inc."},
    "2": {"cik_str": 1652044, "ticker": "GOOG", "title": "Alphabet Inc."},
    "3": {"cik_str": 789019, "ticker": "msft", "title": "MICROSOFT CORP"},  # lowercase
    "4": {"cik_str": 999001, "ticker": "ABC WS", "title": "Warrant Co"},  # invalid char
    "5": {"cik_str": 999002, "ticker": "XYZ~U", "title": "Unit Co"},  # invalid char
    "6": {"cik_str": 1067983, "ticker": "BRK-B", "title": "Berkshire Hathaway"},
    "7": {"cik_str": 320193, "ticker": "AAPL", "title": "Apple Inc. dup"},  # dup ticker
    "8": {"cik_str": 555555, "ticker": "OLDCO", "title": "Stale Filer Inc"},
}


class FakeMotherConn:
    """Stands in for an asyncpg.Connection: fetch() answers by query text."""

    def __init__(
        self,
        active_ciks: list[int],
        fundamentals: list[dict[str, Any]],
    ) -> None:
        self._active_ciks = active_ciks
        self._fundamentals = fundamentals
        self.queries: list[str] = []
        self.closed = False

    async def fetch(self, query: str, *args: Any) -> list[dict[str, Any]]:
        self.queries.append(query)
        if "GROUP BY cik" in query and "HAVING" in query:
            return [
                {"cik": cik, "latest_period_end": dt.date(2026, 3, 31)}
                for cik in self._active_ciks
            ]
        if "WHERE cik = ANY($1)" in query:
            wanted = set(args[0])
            return [row for row in self._fundamentals if row["cik"] in wanted]
        raise AssertionError(f"Unexpected mother-DB query: {query}")

    async def close(self) -> None:
        self.closed = True


def _fund_row(cik: int, **overrides: Any) -> dict[str, Any]:
    row: dict[str, Any] = {
        "cik": cik,
        "period_end": dt.date(2026, 3, 31),
        "book_equity": 100.0,
        "total_assets": 500.0,
        "net_income_ttm": 50.0,
        "revenue": 200.0,
        "gross_profit": 80.0,
        "shares_outstanding": 1000.0,
        "quality_roa": 0.1,
        "investment_growth": 0.05,
        "profitability_gross": 0.4,
        "source_filing_date": dt.date(2026, 4, 15),
    }
    row.update(overrides)
    return row


ACTIVE_CIKS = [320193, 1652044, 789019, 999001, 999002, 1067983]
FUNDAMENTALS = [_fund_row(cik) for cik in ACTIVE_CIKS]


class FakeSession:
    """Async-session stand-in recording executed statements and commits."""

    def __init__(self) -> None:
        self.executed: list[object] = []
        self.commits = 0
        self.rollbacks = 0

    async def __aenter__(self) -> "FakeSession":
        return self

    async def __aexit__(self, *args: object) -> None:
        return None

    async def execute(self, stmt: object) -> None:
        self.executed.append(stmt)

    async def commit(self) -> None:
        self.commits += 1

    async def rollback(self) -> None:
        self.rollbacks += 1


def _compiled(stmt: object) -> str:
    return str(
        stmt.compile(  # type: ignore[attr-defined]
            dialect=postgresql.dialect(), compile_kwargs={"literal_binds": False}
        )
    )


# ---------------------------------------------------------------------------
# SEC JSON parsing / normalization
# ---------------------------------------------------------------------------


def test_parse_sec_company_tickers_normalizes_and_dedupes() -> None:
    rows = parse_sec_company_tickers(SEC_RAW)
    tickers = [r.ticker for r in rows]
    # Uppercased, exact-duplicate ticker dropped (first occurrence wins).
    assert "MSFT" in tickers
    assert tickers.count("AAPL") == 1
    # Multi-class CIK keeps BOTH tickers (each is a tradable line).
    assert "GOOG" in tickers and "GOOGL" in tickers
    assert len(rows) == 8  # 9 raw entries - 1 duplicate AAPL


def test_parse_sec_company_tickers_keeps_cik_and_title() -> None:
    rows = {r.ticker: r for r in parse_sec_company_tickers(SEC_RAW)}
    assert rows["AAPL"].cik == 320193
    assert rows["AAPL"].title == "Apple Inc."
    assert rows["MSFT"].cik == 789019


@pytest.mark.parametrize(
    ("ticker", "valid"),
    [
        ("AAPL", True),
        ("BRK-B", True),
        ("BF.B", True),
        ("A1B2", True),
        ("ABC WS", False),
        ("XYZ~U", False),
        ("AB/C", False),
        ("", False),
        ("aapl", False),  # validation happens after uppercase normalization
    ],
)
def test_is_valid_universe_ticker(ticker: str, valid: bool) -> None:
    assert is_valid_universe_ticker(ticker) is valid


# ---------------------------------------------------------------------------
# Universe selection (active-CIK filter + exclusions)
# ---------------------------------------------------------------------------


def test_select_universe_filters_by_active_cik_and_validity() -> None:
    sec_rows = parse_sec_company_tickers(SEC_RAW)
    active = set(ACTIVE_CIKS)  # OLDCO's CIK 555555 is NOT active
    matched, excluded, multi_class = select_universe(sec_rows, active)
    matched_tickers = {r.ticker for r in matched}
    assert matched_tickers == {"AAPL", "GOOGL", "GOOG", "MSFT", "BRK-B"}
    assert "OLDCO" not in matched_tickers  # inactive CIK
    assert excluded == 2  # ABC WS and XYZ~U (active CIKs, invalid chars)
    assert multi_class == 1  # Alphabet's two share classes


def test_select_universe_empty_active_set() -> None:
    sec_rows = parse_sec_company_tickers(SEC_RAW)
    matched, excluded, multi_class = select_universe(sec_rows, set())
    assert matched == [] and excluded == 0 and multi_class == 0


# ---------------------------------------------------------------------------
# Upsert statement builders (compiled SQL)
# ---------------------------------------------------------------------------


def test_universe_upsert_is_on_conflict_do_update() -> None:
    rows = [SecTickerRow(cik=320193, ticker="AAPL", title="Apple Inc.")]
    sql = _compiled(build_universe_upsert(rows, _NOW))
    assert "INSERT INTO universe_constituents" in sql
    assert "ON CONFLICT (ticker) DO UPDATE" in sql
    assert "synced_at" in sql


def test_universe_upsert_preserves_status_on_conflict() -> None:
    """status must NOT be in the DO UPDATE SET clause: 'no_tiingo_data' marks
    set by the backfill must survive re-syncs."""
    rows = [SecTickerRow(cik=320193, ticker="AAPL", title="Apple Inc.")]
    sql = _compiled(build_universe_upsert(rows, _NOW))
    set_clause = sql.split("DO UPDATE SET", 1)[1]
    assert "status" not in set_clause
    assert "cik = excluded.cik" in set_clause
    assert "synced_at = excluded.synced_at" in set_clause


def test_universe_upsert_rejects_empty() -> None:
    with pytest.raises(ValueError):
        build_universe_upsert([], _NOW)


def test_fundamentals_upsert_is_on_conflict_do_update() -> None:
    record = {"ticker": "AAPL", "synced_at": _NOW} | {
        k: v for k, v in _fund_row(320193).items()
    }
    sql = _compiled(build_fundamentals_upsert([record]))
    assert "INSERT INTO fundamentals_snapshot" in sql
    assert "ON CONFLICT (ticker) DO UPDATE" in sql
    set_clause = sql.split("DO UPDATE SET", 1)[1]
    for col in (
        "period_end",
        "book_equity",
        "net_income_ttm",
        "shares_outstanding",
        "synced_at",
    ):
        assert f"{col} = excluded.{col}" in set_clause


def test_fundamentals_upsert_rejects_empty() -> None:
    with pytest.raises(ValueError):
        build_fundamentals_upsert([])


# ---------------------------------------------------------------------------
# DSN handling
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "raw",
    [
        "postgresql+asyncpg://u:p@host:5432/mother",
        "postgresql+psycopg://u:p@host:5432/mother",
        "postgresql://u:p@host:5432/mother",
    ],
)
def test_mother_db_dsn_strips_driver_qualifier(
    monkeypatch: pytest.MonkeyPatch, raw: str
) -> None:
    from app.core import config

    monkeypatch.setenv("INVESTINTELL_DB_URL", raw)
    config.get_settings.cache_clear()
    try:
        assert mother_db_dsn() == "postgresql://u:p@host:5432/mother"
    finally:
        config.get_settings.cache_clear()


def test_mother_db_dsn_missing_fails_loud(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.core import config

    monkeypatch.setenv("INVESTINTELL_DB_URL", "")
    config.get_settings.cache_clear()
    try:
        with pytest.raises(RuntimeError, match="INVESTINTELL_DB_URL"):
            mother_db_dsn()
    finally:
        config.get_settings.cache_clear()


# ---------------------------------------------------------------------------
# run_sync orchestration (fakes — no network, no DB)
# ---------------------------------------------------------------------------


async def _download_fake() -> dict[str, Any]:
    return SEC_RAW


def test_run_sync_real_writes_and_reports(tmp_path: Path) -> None:
    import asyncio

    conn = FakeMotherConn(ACTIVE_CIKS, FUNDAMENTALS)
    session = FakeSession()

    report = asyncio.run(
        run_sync(
            download=_download_fake,
            connect_mother=_make_connector(conn),
            session_factory=lambda: session,  # type: ignore[arg-type,return-value]
            seeds_dir=tmp_path,
        )
    )

    assert report.sec_rows == 8
    assert report.active_ciks == 6
    assert report.matched_tickers == 5
    assert report.sec_excluded_invalid == 2
    assert report.multi_class_ciks == 1
    assert report.universe_upserted == 5
    assert report.fundamentals_upserted == 5
    assert report.fundamentals_missing_ciks == 0
    # Mother connection always closed; local session committed once.
    assert conn.closed is True
    assert session.commits == 1
    assert session.rollbacks == 0
    # Universe upsert chunk + fundamentals upsert chunk.
    assert len(session.executed) == 2
    # Dated snapshot written and parseable.
    snapshots = list(tmp_path.glob("sec_company_tickers_*.json"))
    assert len(snapshots) == 1
    assert json.loads(snapshots[0].read_text(encoding="utf-8")) == SEC_RAW


def test_run_sync_dry_run_writes_nothing(tmp_path: Path) -> None:
    import asyncio

    conn = FakeMotherConn(ACTIVE_CIKS, FUNDAMENTALS)

    def _forbidden_session() -> FakeSession:
        raise AssertionError("dry run must not open a local DB session")

    report = asyncio.run(
        run_sync(
            dry_run=True,
            download=_download_fake,
            connect_mother=_make_connector(conn),
            session_factory=_forbidden_session,  # type: ignore[arg-type]
            seeds_dir=tmp_path,
        )
    )

    assert report.dry_run is True
    assert report.matched_tickers == 5
    assert report.universe_upserted == 0
    assert report.fundamentals_upserted == 0
    assert list(tmp_path.iterdir()) == []  # no snapshot written
    assert conn.closed is True  # mother conn still opened (read-only) and closed


def test_run_sync_counts_missing_fundamentals(tmp_path: Path) -> None:
    """An active CIK with no fundamentals row keeps its constituent but gets
    no snapshot — counted loudly, never raises."""
    import asyncio

    fundamentals_missing_apple = [r for r in FUNDAMENTALS if r["cik"] != 320193]
    conn = FakeMotherConn(ACTIVE_CIKS, fundamentals_missing_apple)
    session = FakeSession()

    report = asyncio.run(
        run_sync(
            download=_download_fake,
            connect_mother=_make_connector(conn),
            session_factory=lambda: session,  # type: ignore[arg-type,return-value]
            seeds_dir=tmp_path,
        )
    )

    assert report.matched_tickers == 5
    assert report.fundamentals_missing_ciks == 1
    assert report.universe_upserted == 5
    assert report.fundamentals_upserted == 4  # AAPL has no snapshot


def test_run_sync_closes_mother_conn_on_error(tmp_path: Path) -> None:
    import asyncio

    class ExplodingConn(FakeMotherConn):
        async def fetch(self, query: str, *args: Any) -> list[dict[str, Any]]:
            raise RuntimeError("mother db exploded")

    conn = ExplodingConn(ACTIVE_CIKS, FUNDAMENTALS)
    with pytest.raises(RuntimeError, match="mother db exploded"):
        asyncio.run(
            run_sync(
                dry_run=True,
                download=_download_fake,
                connect_mother=_make_connector(conn),
                seeds_dir=tmp_path,
            )
        )
    assert conn.closed is True


def _make_connector(conn: FakeMotherConn) -> Any:
    async def _connect() -> FakeMotherConn:
        return conn

    return _connect
