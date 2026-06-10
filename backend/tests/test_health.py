"""Tests for the /health endpoint.

These tests run WITHOUT the Docker DB — they use in-process ASGI transport.
The 503 test verifies the fail-loud contract: a bad database_url must not be
masked and must not return 200 with a degraded payload.
"""

from unittest.mock import patch

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.exc import SQLAlchemyError

from app.main import create_app

# ---------------------------------------------------------------------------
# Happy-path: app boots and OpenAPI schema includes /health
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_openapi_includes_health_route(client: "AsyncClient") -> None:
    response = await client.get("/openapi.json")
    assert response.status_code == 200
    paths = response.json()["paths"]
    assert "/health" in paths, f"/health not found in OpenAPI paths: {list(paths.keys())}"


# ---------------------------------------------------------------------------
# Fail-loud contract: unreachable DB → 503 with error detail
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_health_returns_503_when_db_unreachable() -> None:
    """Mock AsyncSessionLocal so the route raises deterministically; /health must return 503."""
    app = create_app()

    class _FakeSession:
        async def __aenter__(self) -> "_FakeSession":
            return self

        async def __aexit__(self, *args: object) -> None:
            pass

        async def execute(self, *args: object, **kwargs: object) -> None:
            raise SQLAlchemyError("injected DB failure")

    with patch("app.api.routes.health.AsyncSessionLocal", return_value=_FakeSession()):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            response = await ac.get("/health")

    assert response.status_code == 503
    body = response.json()
    assert "detail" in body
    assert body["detail"]  # non-empty error message
