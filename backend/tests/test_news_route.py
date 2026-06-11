"""Tests for GET /stocks/{ticker}/news.

The ingestion function and DB read helper are stubbed at the route-module
boundary; the Tiingo client and DB session dependencies are overridden.
No live network, no live DB.
"""

import datetime as dt
from types import SimpleNamespace
from typing import Any

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from app.api.routes import stocks
from app.core.db import get_session
from app.core.tiingo_provider import get_tiingo_client
from app.main import create_app
from app.tiingo.exceptions import TiingoRateLimitError, TiingoServerError

_PUBLISHED = dt.datetime(2026, 6, 9, 14, 30, tzinfo=dt.UTC)


def _row(item_id: int) -> SimpleNamespace:
    return SimpleNamespace(
        id=item_id,
        title=f"Headline {item_id}",
        url=f"https://example.com/{item_id}",
        source="example.com",
        description=f"Description {item_id}" if item_id % 2 else None,
        published_at=_PUBLISHED - dt.timedelta(hours=item_id),
    )


def _app_with_overrides() -> FastAPI:
    app = create_app()
    app.dependency_overrides[get_session] = lambda: None
    app.dependency_overrides[get_tiingo_client] = lambda: object()
    return app


def _install_stubs(
    monkeypatch: pytest.MonkeyPatch,
    rows: list[SimpleNamespace],
    ensure_error: Exception | None = None,
) -> dict[str, list[Any]]:
    calls: dict[str, list[Any]] = {"ensure": [], "select": []}

    async def fake_ensure(session: Any, client: Any, ticker: str, limit: int = 50) -> int:
        calls["ensure"].append((ticker, limit))
        if ensure_error is not None:
            raise ensure_error
        return len(rows)

    async def fake_select(session: Any, ticker: str, limit: int) -> list[SimpleNamespace]:
        calls["select"].append((ticker, limit))
        return rows[:limit]

    monkeypatch.setattr(stocks, "ensure_news", fake_ensure)
    monkeypatch.setattr(stocks, "_select_news_rows", fake_select)
    return calls


async def _get(path: str) -> Any:
    transport = ASGITransport(app=_app_with_overrides())
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        return await ac.get(path)


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------


async def test_happy_path_returns_items_not_stale(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = _install_stubs(monkeypatch, rows=[_row(1), _row(2)])
    response = await _get("/stocks/aapl/news")

    assert response.status_code == 200
    body = response.json()
    assert body["ticker"] == "AAPL"
    assert body["count"] == 2
    assert body["stale"] is False
    assert [item["id"] for item in body["items"]] == [1, 2]
    first = body["items"][0]
    assert set(first) == {"id", "title", "url", "source", "description", "published_at"}
    assert dt.datetime.fromisoformat(first["published_at"]) == _PUBLISHED - dt.timedelta(
        hours=1
    )
    # Route normalizes the symbol before handing it to ingestion and the read.
    assert calls["ensure"] == [("AAPL", 50)]
    assert calls["select"] == [("AAPL", 20)]


async def test_empty_news_is_a_legit_200_with_count_zero(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_stubs(monkeypatch, rows=[])
    response = await _get("/stocks/ZNEWS/news")

    assert response.status_code == 200
    body = response.json()
    assert body == {"ticker": "ZNEWS", "count": 0, "stale": False, "items": []}


async def test_limit_is_applied_to_the_read(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = _install_stubs(monkeypatch, rows=[_row(i) for i in range(1, 11)])
    response = await _get("/stocks/AAPL/news?limit=3")

    assert response.status_code == 200
    assert response.json()["count"] == 3
    assert calls["select"] == [("AAPL", 3)]


# ---------------------------------------------------------------------------
# Degrade-to-cache (declared, never silent)
# ---------------------------------------------------------------------------


async def test_fetch_failure_with_cache_serves_stale_true(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_stubs(
        monkeypatch,
        rows=[_row(1)],
        ensure_error=TiingoRateLimitError("429 after retries"),
    )
    response = await _get("/stocks/AAPL/news")

    assert response.status_code == 200
    body = response.json()
    assert body["stale"] is True
    assert body["count"] == 1
    assert body["items"][0]["id"] == 1


async def test_rate_limit_without_cache_returns_503(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_stubs(monkeypatch, rows=[], ensure_error=TiingoRateLimitError("429"))
    response = await _get("/stocks/AAPL/news")

    assert response.status_code == 503
    assert "rate limit" in response.json()["detail"].lower()


async def test_server_error_without_cache_returns_502(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_stubs(monkeypatch, rows=[], ensure_error=TiingoServerError("HTTP 500"))
    response = await _get("/stocks/AAPL/news")

    assert response.status_code == 502
    assert "News provider error" in response.json()["detail"]


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("bad_ticker", ["ABCDEFGHIJK", "AA%24PL", "%20%20"])
async def test_absurd_ticker_returns_422(
    monkeypatch: pytest.MonkeyPatch, bad_ticker: str
) -> None:
    calls = _install_stubs(monkeypatch, rows=[_row(1)])
    response = await _get(f"/stocks/{bad_ticker}/news")

    assert response.status_code == 422
    assert "Invalid ticker" in response.json()["detail"]
    assert calls["ensure"] == []  # rejected before any ingestion work


async def test_dotted_and_hyphenated_tickers_are_accepted(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_stubs(monkeypatch, rows=[])
    assert (await _get("/stocks/BRK.B/news")).status_code == 200
    assert (await _get("/stocks/BF-B/news")).status_code == 200


@pytest.mark.parametrize("limit", [0, 51, -1])
async def test_limit_out_of_bounds_returns_422(
    monkeypatch: pytest.MonkeyPatch, limit: int
) -> None:
    _install_stubs(monkeypatch, rows=[])
    response = await _get(f"/stocks/AAPL/news?limit={limit}")
    assert response.status_code == 422
