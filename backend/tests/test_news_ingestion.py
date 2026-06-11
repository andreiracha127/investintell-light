"""Tests for the on-demand-with-cache news ingestion (app/ingestion/news.py).

No live network, no live DB. Upsert correctness is tested by compiling the
statement against the PostgreSQL dialect; orchestration uses a thin fake
session (same approach as the EOD ingestion tests).
"""

import datetime as dt
from unittest.mock import AsyncMock

import pytest
from sqlalchemy.dialects import postgresql
from sqlalchemy.dialects.postgresql import Insert as PgInsert

from app.ingestion.news import _NEWS_COLUMNS, build_news_upsert, ensure_news
from app.tiingo.models import TiingoNewsItem

_NOW = dt.datetime.now(dt.UTC)


def _news_item(item_id: int = 1, tickers: list[str] | None = None) -> TiingoNewsItem:
    return TiingoNewsItem(
        id=item_id,
        title=f"Title {item_id}",
        url=f"https://example.com/{item_id}",
        published_date=dt.datetime(2026, 6, 9, 12, 0, tzinfo=dt.UTC),
        source="example.com",
        description="A description",
        tickers=tickers if tickers is not None else ["aapl", "msft"],
    )


class _FakeSession:
    """Thin stand-in: scalar() returns max(fetched_at); execute is recorded."""

    def __init__(self, last_fetched: dt.datetime | None) -> None:
        self._last_fetched = last_fetched
        self.executed: list[object] = []
        self.commits = 0
        self.rollbacks = 0
        self.execute_error: Exception | None = None

    async def scalar(self, stmt: object) -> dt.datetime | None:
        return self._last_fetched

    async def execute(self, stmt: object) -> None:
        if self.execute_error is not None:
            raise self.execute_error
        self.executed.append(stmt)

    async def commit(self) -> None:
        self.commits += 1

    async def rollback(self) -> None:
        self.rollbacks += 1


# ---------------------------------------------------------------------------
# Statement construction
# ---------------------------------------------------------------------------


def test_news_upsert_targets_id_and_updates_all_article_fields() -> None:
    sql = str(
        build_news_upsert([_news_item(1), _news_item(2)]).compile(
            dialect=postgresql.dialect()
        )
    )
    assert "ON CONFLICT (id) DO UPDATE" in sql
    for col in _NEWS_COLUMNS:
        assert f"{col} = excluded.{col}" in sql
    # Refreshes must count toward freshness: fetched_at bumped on conflict.
    assert "fetched_at = now()" in sql


def test_news_upsert_normalizes_tickers_to_uppercase() -> None:
    stmt = build_news_upsert([_news_item(1, tickers=["aapl", " msft ", ""])])
    compiled = stmt.compile(dialect=postgresql.dialect())
    assert compiled.params["tickers_m0"] == ["AAPL", "MSFT"]


def test_news_upsert_rejects_empty_items() -> None:
    with pytest.raises(ValueError):
        build_news_upsert([])


# ---------------------------------------------------------------------------
# Orchestration (ensure_news)
# ---------------------------------------------------------------------------


async def test_fresh_ticker_skips_client_entirely() -> None:
    session = _FakeSession(last_fetched=_NOW - dt.timedelta(minutes=5))
    client = AsyncMock()

    upserted = await ensure_news(
        session,  # type: ignore[arg-type]
        client,
        "aapl",
        staleness_minutes=30.0,
    )

    client.get_news.assert_not_called()
    assert upserted == 0
    assert session.commits == 0


@pytest.mark.parametrize(
    "last_fetched",
    [None, dt.datetime.now(dt.UTC) - dt.timedelta(minutes=45)],
    ids=["never_fetched", "stale"],
)
async def test_stale_or_unknown_ticker_fetches_and_upserts(
    last_fetched: dt.datetime | None,
) -> None:
    session = _FakeSession(last_fetched=last_fetched)
    client = AsyncMock()
    client.get_news.return_value = [_news_item(1), _news_item(2)]

    upserted = await ensure_news(
        session,  # type: ignore[arg-type]
        client,
        "aapl",
        limit=25,
        staleness_minutes=30.0,
    )

    client.get_news.assert_awaited_once_with(["AAPL"], limit=25)
    assert upserted == 2
    assert session.commits == 1
    assert len(session.executed) == 1
    stmt = session.executed[0]
    assert isinstance(stmt, PgInsert)
    assert stmt.table.name == "news_items"


async def test_stale_ticker_with_zero_articles_returns_zero_without_write() -> None:
    session = _FakeSession(last_fetched=None)
    client = AsyncMock()
    client.get_news.return_value = []

    upserted = await ensure_news(
        session,  # type: ignore[arg-type]
        client,
        "ZNEWS",
        staleness_minutes=30.0,
    )

    assert upserted == 0
    assert session.executed == []
    assert session.commits == 0


async def test_tiingo_error_propagates() -> None:
    from app.tiingo.exceptions import TiingoRateLimitError

    session = _FakeSession(last_fetched=None)
    client = AsyncMock()
    client.get_news.side_effect = TiingoRateLimitError("429")

    with pytest.raises(TiingoRateLimitError):
        await ensure_news(
            session,  # type: ignore[arg-type]
            client,
            "AAPL",
            staleness_minutes=30.0,
        )

    assert session.commits == 0


async def test_upsert_failure_rolls_back_and_reraises() -> None:
    session = _FakeSession(last_fetched=None)
    session.execute_error = RuntimeError("boom")
    client = AsyncMock()
    client.get_news.return_value = [_news_item(1)]

    with pytest.raises(RuntimeError):
        await ensure_news(
            session,  # type: ignore[arg-type]
            client,
            "AAPL",
            staleness_minutes=30.0,
        )

    assert session.rollbacks == 1
    assert session.commits == 0
