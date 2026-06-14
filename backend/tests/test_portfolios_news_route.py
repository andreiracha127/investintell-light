"""Tests for GET /portfolios/{id}/news (aggregate news across portfolio tickers).

Stubs at the module boundaries (portfolio load, ensure_news, news read); the
overlap statement is compile-checked against the PostgreSQL dialect.
No live network, no live DB.
"""

import datetime as dt
from types import SimpleNamespace
from typing import Any

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.dialects import postgresql

from app.api.routes import portfolios
from app.api.routes.portfolios import build_news_overlap_select
from app.core.auth import CurrentUser, get_current_user
from app.core.db import get_session
from app.core.tiingo_provider import get_tiingo_client
from app.main import create_app
from app.services import portfolio_crud
from app.tiingo.exceptions import TiingoRateLimitError, TiingoServerError

_CREATED = dt.datetime(2026, 6, 10, 12, 0, tzinfo=dt.UTC)
_PUBLISHED = dt.datetime(2026, 6, 9, 14, 30, tzinfo=dt.UTC)


def _portfolio(tickers: list[str]) -> SimpleNamespace:
    return SimpleNamespace(
        id=1,
        name="Test",
        cash=0.0,
        created_at=_CREATED,
        updated_at=_CREATED,
        positions=[
            SimpleNamespace(ticker=t, quantity=1.0, acq_price=None) for t in tickers
        ],
    )


def _row(item_id: int) -> SimpleNamespace:
    return SimpleNamespace(
        id=item_id,
        title=f"Headline {item_id}",
        url=f"https://example.com/{item_id}",
        source="example.com",
        description=None,
        published_at=_PUBLISHED - dt.timedelta(hours=item_id),
    )


def _client() -> AsyncClient:
    app = create_app()
    app.dependency_overrides[get_session] = lambda: None
    app.dependency_overrides[get_tiingo_client] = lambda: object()
    app.dependency_overrides[get_current_user] = lambda: CurrentUser(
        sub="u-1", org_id=None, claims={}
    )
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


def _install_stubs(
    monkeypatch: pytest.MonkeyPatch,
    portfolio: SimpleNamespace | None,
    rows: list[SimpleNamespace],
    ensure_error: Exception | None = None,
) -> dict[str, list[Any]]:
    calls: dict[str, list[Any]] = {"ensure": [], "select": []}

    async def fake_get(session: Any, portfolio_id: int) -> SimpleNamespace | None:
        return portfolio

    async def fake_ensure(
        session: Any, client: Any, tickers: Any, limit: int = 50, **kw: Any
    ) -> int:
        calls["ensure"].append((list(tickers), limit))
        if ensure_error is not None:
            raise ensure_error
        return len(rows)

    async def fake_select(
        session: Any, tickers: Any, limit: int
    ) -> list[SimpleNamespace]:
        calls["select"].append((list(tickers), limit))
        return rows[:limit]

    monkeypatch.setattr(portfolio_crud, "get_portfolio", fake_get)
    monkeypatch.setattr(portfolios, "ensure_news", fake_ensure)
    monkeypatch.setattr(portfolios, "_select_portfolio_news_rows", fake_select)
    return calls


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------


async def test_happy_path_one_combined_ensure_for_all_tickers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = _install_stubs(
        monkeypatch, _portfolio(["AAPL", "MSFT"]), rows=[_row(1), _row(2)]
    )
    async with _client() as ac:
        response = await ac.get("/portfolios/1/news")

    assert response.status_code == 200
    body = response.json()
    assert body["portfolio_id"] == 1
    assert body["tickers"] == ["AAPL", "MSFT"]
    assert body["count"] == 2
    assert body["stale"] is False
    assert [item["id"] for item in body["items"]] == [1, 2]
    # ONE ensure call covering the whole portfolio, fetch limit from settings.
    assert calls["ensure"] == [(["AAPL", "MSFT"], 50)]
    assert calls["select"] == [(["AAPL", "MSFT"], 20)]


async def test_limit_is_applied_to_the_read(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = _install_stubs(
        monkeypatch, _portfolio(["AAPL"]), rows=[_row(i) for i in range(1, 11)]
    )
    async with _client() as ac:
        response = await ac.get("/portfolios/1/news?limit=3")

    assert response.status_code == 200
    assert response.json()["count"] == 3
    assert calls["select"] == [(["AAPL"], 3)]


async def test_empty_portfolio_returns_count_zero_without_ensure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = _install_stubs(monkeypatch, _portfolio([]), rows=[_row(1)])
    async with _client() as ac:
        response = await ac.get("/portfolios/1/news")

    assert response.status_code == 200
    assert response.json() == {
        "portfolio_id": 1,
        "tickers": [],
        "count": 0,
        "stale": False,
        "items": [],
    }
    assert calls["ensure"] == []


async def test_missing_portfolio_404(monkeypatch: pytest.MonkeyPatch) -> None:
    _install_stubs(monkeypatch, None, rows=[])
    async with _client() as ac:
        response = await ac.get("/portfolios/999/news")

    assert response.status_code == 404


# ---------------------------------------------------------------------------
# Degrade-to-cache (declared, never silent) — same contract as /stocks news
# ---------------------------------------------------------------------------


async def test_fetch_failure_with_cache_serves_stale_true(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_stubs(
        monkeypatch,
        _portfolio(["AAPL", "MSFT"]),
        rows=[_row(1)],
        ensure_error=TiingoServerError("HTTP 500"),
    )
    async with _client() as ac:
        response = await ac.get("/portfolios/1/news")

    assert response.status_code == 200
    body = response.json()
    assert body["stale"] is True
    assert body["count"] == 1


async def test_server_error_without_cache_returns_502(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_stubs(
        monkeypatch,
        _portfolio(["AAPL"]),
        rows=[],
        ensure_error=TiingoServerError("HTTP 500"),
    )
    async with _client() as ac:
        response = await ac.get("/portfolios/1/news")

    assert response.status_code == 502
    assert "News provider error" in response.json()["detail"]


async def test_rate_limit_without_cache_returns_503(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_stubs(
        monkeypatch,
        _portfolio(["AAPL"]),
        rows=[],
        ensure_error=TiingoRateLimitError("429"),
    )
    async with _client() as ac:
        response = await ac.get("/portfolios/1/news")

    assert response.status_code == 503


@pytest.mark.parametrize("limit", [0, 51, -1])
async def test_limit_out_of_bounds_returns_422(
    monkeypatch: pytest.MonkeyPatch, limit: int
) -> None:
    _install_stubs(monkeypatch, _portfolio(["AAPL"]), rows=[])
    async with _client() as ac:
        response = await ac.get(f"/portfolios/1/news?limit={limit}")

    assert response.status_code == 422


# ---------------------------------------------------------------------------
# Query shape: ARRAY overlap (&&), newest first, bounded
# ---------------------------------------------------------------------------


def test_news_select_uses_array_overlap_ordered_and_bounded() -> None:
    stmt = build_news_overlap_select(["AAPL", "MSFT"], 20)
    compiled = stmt.compile(dialect=postgresql.dialect())
    sql = str(compiled)
    assert "&&" in sql  # ARRAY overlap, not containment
    assert "ORDER BY news_items.published_at DESC" in sql
    assert "LIMIT" in sql
    assert compiled.params["tickers_1"] == ["AAPL", "MSFT"]
