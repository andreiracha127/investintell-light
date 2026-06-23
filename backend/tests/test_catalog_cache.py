"""Cache de catálogo (app/core/cache.py): middleware + fallback de memória.

Sem Redis nos testes — o fail-open garante que o caminho de memória é o
exercitado (mesmo comportamento de produção quando o Redis está fora).
"""

import asyncio

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.core.cache import (
    CACHED_GET_PREFIXES,
    CatalogCacheMiddleware,
    MemoryCache,
    cache_key,
    catalog_cache,
)


def _build_app() -> tuple[FastAPI, dict[str, int]]:
    calls = {"funds": 0, "portfolios": 0}
    app = FastAPI()
    app.add_middleware(CatalogCacheMiddleware)

    @app.get("/funds")
    async def list_funds(q: str = "") -> dict[str, str | int]:
        calls["funds"] += 1
        return {"q": q, "calls": calls["funds"]}

    @app.get("/portfolios")
    async def list_portfolios() -> dict[str, int]:
        calls["portfolios"] += 1
        return {"calls": calls["portfolios"]}

    return app, calls


def test_cached_prefix_serves_second_request_from_cache() -> None:
    app, calls = _build_app()
    with TestClient(app) as client:
        first = client.get("/funds?q=abc")
        second = client.get("/funds?q=abc")
    assert first.headers["x-cache"] == "miss"
    assert second.headers["x-cache"] == "hit"
    assert first.json() == second.json()  # corpo idêntico, função rodou 1x
    assert calls["funds"] == 1


def test_different_query_is_a_different_key() -> None:
    app, calls = _build_app()
    with TestClient(app) as client:
        client.get("/funds?q=a")
        client.get("/funds?q=b")
    assert calls["funds"] == 2


def test_non_catalog_route_is_never_cached() -> None:
    """Rotas de portfólio/usuário NUNCA passam pelo cache."""
    assert not any("/portfolios".startswith(p) for p in CACHED_GET_PREFIXES)
    app, calls = _build_app()
    with TestClient(app) as client:
        r1 = client.get("/portfolios")
        r2 = client.get("/portfolios")
    assert "x-cache" not in r1.headers
    assert "x-cache" not in r2.headers
    assert calls["portfolios"] == 2


def test_memory_cache_ttl_expires() -> None:
    cache = MemoryCache()
    cache.set("k", b"v", "application/json", ttl=0.0)
    assert cache.get("k") is None
    cache.set("k", b"v", "application/json", ttl=60.0)
    assert cache.get("k") == (b"v", "application/json")


def test_cache_key_orders_query_params() -> None:
    """Ordem dos parâmetros não fragmenta o cache."""

    class _Url:
        def __init__(self, path: str, query: str) -> None:
            self.path = path
            self.query = query

    class _Req:
        def __init__(self, path: str, query: str) -> None:
            self.url = _Url(path, query)

    a = cache_key(_Req("/funds", "b=2&a=1"))  # type: ignore[arg-type]
    b = cache_key(_Req("/funds", "a=1&b=2"))  # type: ignore[arg-type]
    assert a == b


def test_stocks_family_is_cached() -> None:
    """Endpoints DB-first de /stocks (EOD) servem do cache na repetição."""
    assert any(
        "/stocks/AAPL/analysis".startswith(p) for p in CACHED_GET_PREFIXES
    )
    calls = {"n": 0}
    app = FastAPI()
    app.add_middleware(CatalogCacheMiddleware)

    @app.get("/stocks/{ticker}/analysis")
    async def analysis(ticker: str, range: str = "1Y") -> dict[str, str | int]:
        calls["n"] += 1
        return {"ticker": ticker, "range": range, "calls": calls["n"]}

    with TestClient(app) as client:
        first = client.get("/stocks/AAPL/analysis?range=5Y")
        second = client.get("/stocks/AAPL/analysis?range=5Y")
    assert first.headers["x-cache"] == "miss"
    assert second.headers["x-cache"] == "hit"
    assert first.json() == second.json()
    assert calls["n"] == 1  # handler rodou 1x; 2ª veio do cache


def test_active_backend_is_memory_without_redis_url() -> None:
    assert asyncio.run(catalog_cache.active_backend()) == "memory"
