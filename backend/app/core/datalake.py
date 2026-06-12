"""Read-only engine/session for the TimescaleDB Cloud data-lake (Frente C).

A SECOND database, never the local one: the data-lake holds the tables
materialized by the standalone workers (repo investintell-datalake-workers),
e.g. ``nport_lookthrough_exposures`` / ``nport_lookthrough_summary``. The
Light only reads them — DB-first, no look-through math in any request path.

The engine is created lazily (first request that needs it) because the DSN is
optional: installations without ``DATALAKE_DB_URL`` keep every other feature
working, and the look-through endpoints fail loudly with 503 instead of
silently returning empty data.
"""

from collections.abc import AsyncGenerator

from fastapi import HTTPException
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.core.config import get_settings

_engine: AsyncEngine | None = None
_sessionmaker: async_sessionmaker[AsyncSession] | None = None


def _normalize_dsn(dsn: str) -> str:
    """Accept plain libpq URLs (postgres:// / postgresql://) → asyncpg driver.

    Tiger DSNs carry ``?sslmode=require`` (libpq); asyncpg's equivalent query
    parameter is ``ssl=require``.
    """
    if dsn.startswith("postgres://"):
        dsn = "postgresql://" + dsn.removeprefix("postgres://")
    if dsn.startswith("postgresql://"):
        dsn = "postgresql+asyncpg://" + dsn.removeprefix("postgresql://")
    return dsn.replace("sslmode=", "ssl=")


def _get_sessionmaker() -> async_sessionmaker[AsyncSession]:
    global _engine, _sessionmaker
    if _sessionmaker is None:
        settings = get_settings()
        if not settings.datalake_db_url:
            raise HTTPException(
                status_code=503,
                detail=(
                    "Data-lake connection not configured (DATALAKE_DB_URL) — "
                    "look-through endpoints are unavailable."
                ),
            )
        _engine = create_async_engine(
            _normalize_dsn(settings.datalake_db_url), pool_pre_ping=True
        )
        _sessionmaker = async_sessionmaker(
            bind=_engine, expire_on_commit=False, class_=AsyncSession
        )
    return _sessionmaker


async def get_datalake_session() -> AsyncGenerator[AsyncSession, None]:
    """FastAPI dependency yielding one read-only data-lake session per request."""
    maker = _get_sessionmaker()
    async with maker() as session:
        yield session


async def get_optional_datalake_session() -> AsyncGenerator[AsyncSession | None, None]:
    """Like get_datalake_session, but yields None when the DSN is unset.

    For routes where the data-lake is only needed conditionally (e.g. the
    rebalance preview only touches it when macro_trigger_enabled) — the
    consumer must fail loudly itself when it needs the session and got None.
    """
    if not get_settings().datalake_db_url:
        yield None
        return
    maker = _get_sessionmaker()
    async with maker() as session:
        yield session
