"""
Database engine and session factory.

Project conventions (non-negotiable):
- All DB access is async (AsyncEngine, AsyncSession).
- expire_on_commit=False: loaded attributes remain accessible after commit without
  an implicit lazy-load that would fail outside a session context.
- When ORM models are introduced, all relationships must declare lazy="raise" so that
  N+1 loads fail loudly at development time rather than silently degrading production.
"""

from collections.abc import AsyncGenerator

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.core.config import get_settings


def _make_engine() -> "AsyncEngine":
    settings = get_settings()
    return create_async_engine(settings.database_url, pool_pre_ping=True)


engine = _make_engine()

AsyncSessionLocal: async_sessionmaker[AsyncSession] = async_sessionmaker(
    bind=engine,
    expire_on_commit=False,
    class_=AsyncSession,
)


async def get_session() -> AsyncGenerator[AsyncSession, None]:
    """FastAPI dependency yielding one AsyncSession per request.

    No implicit commit: route/service code decides transaction boundaries.
    """
    async with AsyncSessionLocal() as session:
        yield session
