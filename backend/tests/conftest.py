import pytest
from httpx import ASGITransport, AsyncClient

from app.main import create_app


@pytest.fixture
async def client() -> "AsyncClient":
    """HTTP test client connected to the default app (live DB not required for schema tests)."""
    transport = ASGITransport(app=create_app())
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


@pytest.fixture(autouse=True)
def _reset_catalog_cache() -> None:
    """O cache de catálogo é um singleton de processo — sem esta limpeza, a
    resposta cacheada de um teste vazaria para o seguinte (mocks diferentes,
    mesma rota)."""
    from app.core.cache import MemoryCache, catalog_cache, portfolio_response_cache

    catalog_cache._memory = MemoryCache()
    portfolio_response_cache._memory = MemoryCache()
