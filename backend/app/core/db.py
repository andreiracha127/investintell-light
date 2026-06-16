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
    # No pool_pre_ping: it adds a round-trip per checkout (costly cross-region)
    # and the latency tail it would mask is handled by pool_recycle + the
    # DB-first request path. Explicit pool bounds keep a slow checkout from
    # hanging or exhausting the shared TimescaleDB Cloud connection ceiling.
    return create_async_engine(
        settings.database_url,
        pool_pre_ping=False,
        pool_size=settings.db_pool_size,
        max_overflow=settings.db_max_overflow,
        pool_timeout=settings.db_pool_timeout_seconds,
        pool_recycle=settings.db_pool_recycle_seconds,
    )


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
