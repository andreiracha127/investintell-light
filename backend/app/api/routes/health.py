import logging

from fastapi import APIRouter, HTTPException
from sqlalchemy import text

from app.core.db import AsyncSessionLocal
from app.schemas.health import HealthResponse

logger = logging.getLogger(__name__)

router = APIRouter()


@router.get("/health", response_model=HealthResponse)
async def health_check() -> HealthResponse:
    """Check service health including database connectivity.

    Returns HTTP 503 with an error detail if the database is unreachable.
    Never returns 200 with a degraded payload — fail loud.
    """
    try:
        async with AsyncSessionLocal() as session:
            await session.execute(text("SELECT 1"))
    except Exception as exc:
        logger.exception("Database health check failed")
        raise HTTPException(
            status_code=503,
            detail="database unreachable",
        ) from exc

    return HealthResponse(status="ok", database="ok")
